"""Downloads raw model output (NOAA GFS, ECMWF IFS open data) from redundant mirrors."""
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import eccodes
import numpy as np
import requests

from . import db, grids
from .config import DOWNLOAD_WORKERS, FORECAST_HOURS, GRID_NLAT, GRID_NLON, GRID_RES

log = logging.getLogger("skymate.ingest")

_session = requests.Session()
_session.headers["User-Agent"] = "SkyMate-Ingest/1.0"


class SourceError(Exception):
    pass


def _get(url: str, headers=None, timeout=60, tries=3) -> bytes:
    last = None
    for attempt in range(tries):
        try:
            r = _session.get(url, headers=headers, timeout=timeout)
            if r.status_code in (200, 206):
                return r.content
            if r.status_code == 404:
                raise SourceError(f"404 {url}")
            last = f"HTTP {r.status_code}"
        except SourceError:
            raise
        except requests.RequestException as e:
            last = str(e)
        time.sleep(2 * (attempt + 1) ** 2)
    raise SourceError(f"{last} {url}")


def _exists(url: str) -> bool:
    try:
        r = _session.head(url, timeout=20)
        return r.status_code == 200
    except requests.RequestException:
        return False


# ─── GRIB decoding ───────────────────────────────────────────────────────────

_TARGET_LATS = 90.0 - GRID_RES * np.arange(GRID_NLAT)
_TARGET_LONS = GRID_RES * np.arange(GRID_NLON)


def decode_field(message: bytes) -> np.ndarray:
    """Decode one GRIB message and resample it onto the SkyMate 0.5 degree grid."""
    if not message.startswith(b"GRIB"):
        raise SourceError("response is not a GRIB message")
    gid = eccodes.codes_new_from_message(message)
    try:
        ni = eccodes.codes_get(gid, "Ni")
        nj = eccodes.codes_get(gid, "Nj")
        lat0 = eccodes.codes_get(gid, "latitudeOfFirstGridPointInDegrees")
        lon0 = eccodes.codes_get(gid, "longitudeOfFirstGridPointInDegrees")
        dlon = eccodes.codes_get(gid, "iDirectionIncrementInDegrees")
        dlat = eccodes.codes_get(gid, "jDirectionIncrementInDegrees")
        north_to_south = eccodes.codes_get(gid, "jScansPositively") == 0
        missing = eccodes.codes_get(gid, "missingValue")
        values = eccodes.codes_get_values(gid).reshape(nj, ni)
    finally:
        eccodes.codes_release(gid)
    values = np.where(values == missing, np.nan, values)
    step_lat = -dlat if north_to_south else dlat
    src_j = np.clip(np.round((_TARGET_LATS - lat0) / step_lat).astype(int), 0, nj - 1)
    src_i = np.round(((_TARGET_LONS - lon0) % 360.0) / dlon).astype(int) % ni
    return values[src_j][:, src_i]


def _check(var: str, field: np.ndarray):
    limits = {"t2m": (-95, 70), "msl": (850, 1090), "rh": (-1, 101), "tcc": (-1, 101)}
    if var in limits:
        lo, hi = limits[var]
        v = field[np.isfinite(field)]
        if v.size == 0 or v.min() < lo or v.max() > hi:
            raise SourceError(f"{var} out of physical range")


# ─── Model definitions ───────────────────────────────────────────────────────

class GFS:
    name = "gfs"
    cycles = [int(c) for c in os.environ.get("SKYMATE_GFS_CYCLES", "0,6,12,18").split(",")]
    mirrors = [
        "https://noaa-gfs-bdp-pds.s3.amazonaws.com",
        "https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod",
        "https://storage.googleapis.com/global-forecast-system",
        "https://noaagfs.blob.core.windows.net/gfs",
    ]
    # var -> (idx VAR, idx LEVEL, converter)
    fields = {
        "t2m": ("TMP", "2 m above ground", lambda x: x - 273.15),
        "rh": ("RH", "2 m above ground", lambda x: x),
        "u10": ("UGRD", "10 m above ground", lambda x: x),
        "v10": ("VGRD", "10 m above ground", lambda x: x),
        "gust": ("GUST", "surface", lambda x: x),
        "msl": ("PRMSL", "mean sea level", lambda x: x / 100),
        "tcc": ("TCDC", "entire atmosphere", lambda x: x),
        "prate": ("PRATE", "surface", lambda x: x * 3600),
        "vis": ("VIS", "surface", lambda x: x),
        "cape": ("CAPE", "surface", lambda x: x),
    }
    landmask = ("LAND", "surface")

    def steps(self, run: datetime) -> list[int]:
        return list(range(0, FORECAST_HOURS + 1, 3))

    def url(self, mirror: str, run: datetime, step: int) -> str:
        d, h = run.strftime("%Y%m%d"), run.strftime("%H")
        return f"{mirror}/gfs.{d}/{h}/atmos/gfs.t{h}z.pgrb2full.0p50.f{step:03d}"

    def ranges(self, mirror: str, run: datetime, step: int, wanted: dict) -> dict[str, tuple[int, int | None]]:
        lines = _get(self.url(mirror, run, step) + ".idx", timeout=30).decode().splitlines()
        entries = []
        for line in lines:
            p = line.split(":")
            if len(p) >= 6:
                entries.append((int(p[1]), p[3], p[4], p[5]))
        out = {}
        for var, (name, level) in wanted.items():
            matches = [(k, e) for k, e in enumerate(entries) if e[1] == name and e[2] == level]
            if not matches:
                continue
            inst = [m for m in matches if "ave" not in m[1][3] and "acc" not in m[1][3]]
            k, e = (inst or matches)[0]
            end = entries[k + 1][0] - 1 if k + 1 < len(entries) else None
            out[var] = (e[0], end)
        return out

    def available(self, run: datetime) -> str | None:
        last = self.steps(run)[-1]
        for m in self.mirrors:
            if _exists(self.url(m, run, last) + ".idx"):
                return m
        return None


class ECMWF:
    name = "ecmwf"
    cycles = [0, 12]
    mirrors = [
        "https://data.ecmwf.int/forecasts",
        "https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com",
        "https://ai4edataeuwest.blob.core.windows.net/ecmwf",
        "https://storage.googleapis.com/ecmwf-open-data",
    ]
    fields = {
        "t2m": ("2t", lambda x: x - 273.15),
        "d2m": ("2d", lambda x: x - 273.15),
        "u10": ("10u", lambda x: x),
        "v10": ("10v", lambda x: x),
        "gust": ("10fg", lambda x: x),
        "msl": ("msl", lambda x: x / 100),
        "tcc": ("tcc", lambda x: x * 100),
        "prate": ("tprate", lambda x: x * 3600),
        "cape": ("mucape", lambda x: x),
    }
    landmask = "lsm"

    def steps(self, run: datetime) -> list[int]:
        s = list(range(0, 145, 3)) + list(range(150, 241, 6))
        return [h for h in s if h <= FORECAST_HOURS]

    def url(self, mirror: str, run: datetime, step: int) -> str:
        d, h = run.strftime("%Y%m%d"), run.strftime("%H")
        return f"{mirror}/{d}/{h}z/ifs/0p25/oper/{d}{h}0000-{step}h-oper-fc.grib2"

    def ranges(self, mirror: str, run: datetime, step: int, wanted: dict) -> dict[str, tuple[int, int | None]]:
        text = _get(self.url(mirror, run, step).replace(".grib2", ".index"), timeout=30).decode()
        by_param = {}
        for line in text.splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("levtype") == "sfc":
                by_param[e["param"]] = (e["_offset"], e["_offset"] + e["_length"] - 1)
        return {var: by_param[param] for var, param in wanted.items() if param in by_param}

    def available(self, run: datetime) -> str | None:
        last = self.steps(run)[-1]
        for m in self.mirrors:
            if _exists(self.url(m, run, last).replace(".grib2", ".index")):
                return m
        return None


MODELS = {"gfs": GFS(), "ecmwf": ECMWF()}
STORED_VARS = list(grids.VARS)


def _fetch_step(model, mirrors: list[str], run: datetime, step: int, want_landmask: bool) -> dict:
    """Fetch and decode one forecast step, trying each mirror in turn."""
    if model.name == "gfs":
        wanted = {v: (n, lvl) for v, (n, lvl, _) in model.fields.items()}
        if want_landmask:
            wanted["_land"] = model.landmask
    else:
        wanted = {v: p for v, (p, _) in model.fields.items()}
        if want_landmask:
            wanted["_land"] = model.landmask
    errors = []
    for mirror in mirrors:
        try:
            rng = model.ranges(mirror, run, step, wanted)
            if "t2m" not in rng:
                raise SourceError("t2m missing from index")
            url = model.url(mirror, run, step)
            raw = {}
            for var, (start, end) in rng.items():
                header = {"Range": f"bytes={start}-{end if end is not None else ''}"}
                field = decode_field(_get(url, headers=header))
                if var == "_land":
                    raw[var] = field
                    continue
                conv = model.fields[var][-1]
                raw[var] = conv(field)
            if "d2m" in raw:
                t, td = raw["t2m"], raw.pop("d2m")
                a, b = 17.625, 243.04
                raw["rh"] = np.clip(100 * np.exp(a * td / (b + td) - a * t / (b + t)), 0, 100)
            for var, f in raw.items():
                _check(var, f)
            db.mark_source(f"{model.name}:{mirror}", True)
            return raw
        except Exception as e:
            errors.append(f"{mirror}: {e}")
            db.mark_source(f"{model.name}:{mirror}", False, str(e))
    raise SourceError(f"step {step} failed on all mirrors: {' | '.join(errors)}")


class IngestLock:
    """Cross-process lock so only one ingester writes a model's grids at a time."""

    def __init__(self, model_name: str):
        self.path = grids.GRID_DIR / f"{model_name}.lock"
        self.fh = None

    def __enter__(self):
        self.fh = open(self.path, "a+")
        try:
            if os.name == "nt":
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.fh.close()
            self.fh = None
            return False
        return True

    def __exit__(self, *exc):
        if self.fh:
            try:
                if os.name == "nt":
                    import msvcrt
                    self.fh.seek(0)
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            finally:
                self.fh.close()


def ingest_run(model_name: str, run: datetime, first_mirror: str | None = None) -> bool:
    with IngestLock(model_name) as locked:
        if not locked:
            log.info("%s ingest already running in another process; skipping", model_name)
            return False
        return _ingest_run(model_name, run, first_mirror)


def _ingest_run(model_name: str, run: datetime, first_mirror: str | None = None) -> bool:
    model = MODELS[model_name]
    rid = grids.run_id(run)
    steps = model.steps(run)
    mirrors = ([first_mirror] if first_mirror else []) + [m for m in model.mirrors if m != first_mirror]
    writer = grids.RunWriter(model_name, run, steps, STORED_VARS)
    pending = writer.pending_steps()
    log.info("Ingesting %s %s: %d/%d steps to download", model_name, rid, len(pending), len(steps))
    with db.tx() as c:
        c.execute("INSERT INTO runs(model, run, status, source) VALUES (?,?,'downloading',?) "
                  "ON CONFLICT(model, run) DO UPDATE SET status='downloading', error=NULL",
                  (model_name, rid, mirrors[0]))
    need_land = grids.landmask() is None
    failures = []

    def work(step):
        fields = _fetch_step(model, mirrors, run, step, need_land and step == 0)
        land = fields.pop("_land", None)
        if land is not None:
            grids.save_landmask(land)
        writer.write_step(step, fields)
        if step in (0, 3):
            grids.save_history(run + timedelta(hours=step), fields)
        return step

    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
        futures = {pool.submit(work, s): s for s in pending}
        for n, fut in enumerate(as_completed(futures), 1):
            try:
                fut.result()
            except Exception as e:
                failures.append(futures[fut])
                log.error("%s %s step %s: %s", model_name, rid, futures[fut], e)
            if n % 10 == 0:
                log.info("%s %s: %d/%d steps", model_name, rid, n, len(pending))

    if failures:
        with db.tx() as c:
            c.execute("UPDATE runs SET status='partial', error=? WHERE model=? AND run=?",
                      (f"{len(failures)} steps failed", model_name, rid))
        log.warning("%s %s incomplete (%d steps failed); will resume next cycle", model_name, rid, len(failures))
        return False

    writer.publish()
    with db.tx() as c:
        c.execute("UPDATE runs SET status='complete', steps=?, finished_at=datetime('now') WHERE model=? AND run=?",
                  (json.dumps(steps), model_name, rid))
    log.info("Published %s %s", model_name, rid)
    return True


def candidate_runs(model_name: str, lookback_hours: int = 48) -> list[datetime]:
    model = MODELS[model_name]
    now = datetime.now(timezone.utc)
    out = []
    t = now.replace(minute=0, second=0, microsecond=0)
    for h in range(lookback_hours):
        c = t - timedelta(hours=h)
        if c.hour in model.cycles and c <= now - timedelta(hours=3):
            out.append(c)
    return out


def ingest_latest(model_name: str) -> bool:
    """Ingest the newest available run that we don't have yet. Returns True if a run was published."""
    have = set(grids.complete_runs(model_name))
    newest_have = max(have) if have else ""
    for run in candidate_runs(model_name):
        rid = grids.run_id(run)
        if rid <= newest_have:
            return False
        mirror = MODELS[model_name].available(run)
        if mirror:
            return ingest_run(model_name, run, mirror)
    return False


def backfill_history(days: int = 7):
    """Fill the history archive from past GFS analyses (only a few small fields per run)."""
    model = MODELS["gfs"]
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=days)).replace(minute=0, second=0, microsecond=0)
    wanted = {v: model.fields[v][:2] for v in grids.HISTORY_VARS}
    todo = []
    t = start.replace(hour=(start.hour // 6) * 6)
    while t < now - timedelta(hours=6):
        for step in (0, 3):
            valid = t + timedelta(hours=step)
            if not (grids.HISTORY_DIR / f"{grids.run_id(valid)}.npz").exists():
                todo.append((t, step))
        t += timedelta(hours=6)
    if not todo:
        return
    log.info("Backfilling %d history slices from GFS archive", len(todo))

    def work(item):
        run, step = item
        for mirror in model.mirrors:
            try:
                rng = model.ranges(mirror, run, step, wanted)
                url = model.url(mirror, run, step)
                fields = {}
                for var, (s, e) in rng.items():
                    fields[var] = model.fields[var][2](decode_field(_get(url, headers={"Range": f"bytes={s}-{e or ''}"})))
                grids.save_history(run + timedelta(hours=step), fields)
                return
            except Exception:
                continue

    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
        list(pool.map(work, todo))
    log.info("History backfill done")
