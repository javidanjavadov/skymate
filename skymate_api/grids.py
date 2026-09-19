"""On-disk storage for forecast grids and the rolling history archive.

Every model is resampled onto one 0.5 degree global grid (lat 90..-90, lon 0..359.5) and stored
as scaled int16 .npy files so point reads are cheap memory-mapped slices.
"""
import json
import logging
import os
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import numpy as np

from .config import GRID_DIR, GRID_NLAT, GRID_NLON, GRID_RES, HISTORY_DAYS, HISTORY_DIR, RUNS_TO_KEEP, STATIC_DIR

log = logging.getLogger("skymate.grids")

NODATA = np.int16(-32768)

# var -> (scale, offset); stored = round((value - offset) / scale)
VARS = {
    "t2m": (0.01, 0.0),     # C
    "rh": (0.01, 0.0),      # %
    "u10": (0.01, 0.0),     # m/s
    "v10": (0.01, 0.0),     # m/s
    "gust": (0.01, 0.0),    # m/s
    "msl": (0.01, 1000.0),  # hPa
    "tcc": (0.01, 0.0),     # %
    "prate": (0.01, 0.0),   # mm/h
    "vis": (1.0, 0.0),      # m
    "cape": (1.0, 0.0),     # J/kg
}
HISTORY_VARS = ("t2m", "prate", "tcc")


def encode(var: str, field: np.ndarray) -> np.ndarray:
    scale, offset = VARS[var]
    out = np.round((field - offset) / scale)
    bad = ~np.isfinite(out)
    out = np.clip(np.where(bad, 0, out), -32767, 32767).astype(np.int16)
    out[bad] = NODATA
    return out


def decode(var: str, raw: np.ndarray) -> np.ndarray:
    scale, offset = VARS[var]
    out = raw.astype(np.float64) * scale + offset
    return np.where(raw == NODATA, np.nan, out)


def run_id(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H")


def parse_run(rid: str) -> datetime:
    return datetime.strptime(rid, "%Y%m%d%H").replace(tzinfo=timezone.utc)


class RunWriter:
    """Writes a run into a .partial directory; resumable after a crash, atomically published."""

    def __init__(self, model: str, run: datetime, steps: list[int], variables: list[str]):
        self.model, self.run, self.steps, self.vars = model, run, steps, variables
        self.final = GRID_DIR / model / run_id(run)
        self.dir = GRID_DIR / model / (run_id(run) + ".partial")
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._progress_file = self.dir / "progress.json"
        meta_file = self.dir / "meta.json"
        if meta_file.exists() and json.loads(meta_file.read_text())["steps"] != steps:
            shutil.rmtree(self.dir)
            self.dir.mkdir(parents=True)
        meta_file.write_text(json.dumps({"model": model, "run": run_id(run), "steps": steps, "vars": variables}))
        self.done = set(json.loads(self._progress_file.read_text())) if self._progress_file.exists() else set()
        shape = (len(steps), GRID_NLAT, GRID_NLON)
        self.arrays = {}
        for v in variables:
            path = self.dir / f"{v}.npy"
            if path.exists():
                self.arrays[v] = np.lib.format.open_memmap(path, mode="r+")
            else:
                arr = np.lib.format.open_memmap(path, mode="w+", dtype=np.int16, shape=shape)
                arr[:] = NODATA
                self.arrays[v] = arr

    def pending_steps(self) -> list[int]:
        return [s for s in self.steps if s not in self.done]

    def write_step(self, step: int, fields: dict[str, np.ndarray]):
        i = self.steps.index(step)
        for v, field in fields.items():
            if v in self.arrays:
                self.arrays[v][i] = encode(v, field)
        with self._lock:
            self.done.add(step)
            self._progress_file.write_text(json.dumps(sorted(self.done)))

    def close(self):
        for arr in self.arrays.values():
            arr.flush()
            _close(arr)
        self.arrays.clear()

    def publish(self):
        self.close()
        meta = json.loads((self.dir / "meta.json").read_text())
        meta["completed_at"] = datetime.now(timezone.utc).isoformat()
        _open_run.cache_clear()
        for attempt in range(10):
            try:
                if self.final.exists():
                    shutil.rmtree(self.final)
                self.dir.rename(self.final)
                break
            except OSError:
                if attempt == 9:
                    raise
                time.sleep(3)
        (self.final / "progress.json").unlink(missing_ok=True)
        (self.final / "meta.json").write_text(json.dumps(meta))
        cleanup(self.model)


def _close(arr):
    mm = getattr(arr, "_mmap", None)
    if mm is not None:
        mm.close()


def cleanup(model: str):
    base = GRID_DIR / model
    if not base.exists():
        return
    complete = sorted(p for p in base.iterdir() if p.is_dir() and not p.name.endswith(".partial"))
    keep = set(complete_runs(model)[:RUNS_TO_KEEP])
    for old in complete:
        if old.name in keep:
            continue
        _open_run.cache_clear()
        (old / "meta.json").unlink(missing_ok=True)
        shutil.rmtree(old, ignore_errors=True)
    for p in base.glob("*.partial"):
        if time.time() - p.stat().st_mtime > 36 * 3600:
            shutil.rmtree(p, ignore_errors=True)
    cutoff = run_id(datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)) if HISTORY_DAYS > 0 else ""
    for f in HISTORY_DIR.glob("*.npz"):
        if ".tmp" in f.name and time.time() - f.stat().st_mtime > 3600:
            f.unlink(missing_ok=True)
        elif f.stem < cutoff:
            f.unlink(missing_ok=True)


def _is_complete(p) -> bool:
    try:
        return p.is_dir() and not p.name.endswith(".partial") and \
            "completed_at" in json.loads((p / "meta.json").read_text())
    except (OSError, ValueError):
        return False


def complete_runs(model: str) -> list[str]:
    base = GRID_DIR / model
    if not base.exists():
        return []
    return sorted((p.name for p in base.iterdir() if _is_complete(p)), reverse=True)


class Run:
    """A published run. Files are opened per read and closed immediately, so runs can be deleted safely."""

    def __init__(self, model: str, rid: str):
        self.dir = GRID_DIR / model / rid
        self.meta = json.loads((self.dir / "meta.json").read_text())
        self.model = model
        self.run = parse_run(rid)
        self.steps = self.meta["steps"]
        self.times = [self.run + timedelta(hours=h) for h in self.steps]

    @property
    def arrays(self):
        return _ArraySet(self.dir, self.meta["vars"])

    def point(self, lat: float, lon: float) -> dict[str, np.ndarray]:
        with self.arrays as arrays:
            return self._point(arrays, lat, lon)

    def _point(self, arrays, lat: float, lon: float) -> dict[str, np.ndarray]:
        """Bilinear interpolation of every variable at (lat, lon) for all steps."""
        y = (90.0 - lat) / GRID_RES
        x = (lon % 360.0) / GRID_RES
        j0 = int(np.clip(np.floor(y), 0, GRID_NLAT - 2))
        i0 = int(np.floor(x)) % GRID_NLON
        i1 = (i0 + 1) % GRID_NLON
        fy, fx = y - j0, x - np.floor(x)
        w = np.array([(1 - fy) * (1 - fx), (1 - fy) * fx, fy * (1 - fx), fy * fx])
        out = {}
        for v, arr in arrays.items():
            corners = np.stack([arr[:, j0, i0], arr[:, j0, i1], arr[:, j0 + 1, i0], arr[:, j0 + 1, i1]], axis=1)
            vals = decode(v, corners)
            valid = np.isfinite(vals)
            ww = np.where(valid, w, 0.0)
            wsum = ww.sum(axis=1)
            with np.errstate(invalid="ignore", divide="ignore"):
                out[v] = np.where(wsum > 0, np.nansum(np.where(valid, vals, 0) * ww, axis=1) / wsum, np.nan)
        return out

    def field(self, var: str, step_index: int) -> np.ndarray:
        arr = np.load(self.dir / f"{var}.npy", mmap_mode="r")
        try:
            return decode(var, np.array(arr[step_index]))
        finally:
            _close(arr)


class _ArraySet:
    def __init__(self, d, variables):
        self.d, self.vars, self.arrays = d, variables, {}

    def __enter__(self):
        self.arrays = {v: np.load(self.d / f"{v}.npy", mmap_mode="r") for v in self.vars}
        return self.arrays

    def __exit__(self, *exc):
        for a in self.arrays.values():
            _close(a)
        self.arrays = {}


@lru_cache(maxsize=16)
def _open_run(model: str, rid: str) -> Run:
    return Run(model, rid)


def open_run(model: str, rid: str) -> Run:
    return _open_run(model, rid)


# ─── Land mask (for drawing coastlines on our own maps) ──────────────────────

LANDMASK = STATIC_DIR / "landmask.npy"


def save_landmask(field: np.ndarray):
    if not LANDMASK.exists():
        np.save(LANDMASK, field.astype(np.float32))


def landmask() -> np.ndarray | None:
    return np.load(LANDMASK) if LANDMASK.exists() else None


# ─── History archive ─────────────────────────────────────────────────────────

def save_history(valid: datetime, fields: dict[str, np.ndarray]):
    path = HISTORY_DIR / f"{run_id(valid)}.npz"
    if path.exists() or not all(v in fields for v in HISTORY_VARS):
        return
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.{threading.get_ident()}.tmp.npz")
    np.savez_compressed(tmp, **{v: encode(v, fields[v]) for v in HISTORY_VARS})
    tmp.replace(path)


def history_point(lat: float, lon: float, start: datetime, end: datetime) -> list[dict]:
    j = int(round((90.0 - lat) / GRID_RES))
    i = int(round((lon % 360.0) / GRID_RES)) % GRID_NLON
    lo, hi = run_id(start), run_id(end)
    out = []
    for f in sorted(HISTORY_DIR.glob("*.npz")):
        if ".tmp" in f.name or not (lo <= f.stem <= hi):
            continue
        try:
            with np.load(f) as z:
                row = {"time": parse_run(f.stem)}
                for v in HISTORY_VARS:
                    val = decode(v, np.asarray(z[v][j, i]))
                    row[v] = None if np.isnan(val) else float(val)
                out.append(row)
        except Exception as e:
            log.warning("Unreadable history file %s: %s", f.name, e)
    return out
