"""Weather maps rendered entirely from SkyMate's own grids."""
import io
from datetime import datetime, timezone
from functools import lru_cache

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from . import geo, grids
from .config import GRID_NLAT, GRID_NLON, GRID_RES, MODELS

LAYERS = {
    "temperature": ("t2m", "RdYlBu_r", "Temperature (°C)"),
    "precipitation": ("prate", "Blues", "Precipitation (mm/h)"),
    "wind": (None, "viridis", "Wind speed (m/s)"),
    "clouds": ("tcc", "Greys", "Cloud cover (%)"),
}


def _latest_run():
    now = datetime.now(timezone.utc)
    best = None
    for m in MODELS:
        runs = grids.complete_runs(m)
        if runs:
            r = grids.open_run(m, runs[0])
            if r.times[-1] >= now and (best is None or r.run > best.run):
                best = r
    return best


def render(lat: float, lon: float, layer: str = "temperature", radius: float = 6.0) -> bytes:
    run = _latest_run()
    if run is None:
        raise LookupError("No stored grid available for maps yet")
    now = datetime.now(timezone.utc)
    k = min(range(len(run.times)), key=lambda i: abs((run.times[i] - now).total_seconds()))
    return _render(run.model, grids.run_id(run.run), k, round(lat, 1), round(lon, 1), layer, radius)


@lru_cache(maxsize=256)
def _render(model, rid, k, lat, lon, layer, radius) -> bytes:
    run = grids.open_run(model, rid)
    var, cmap, label = LAYERS[layer]
    n = int(radius / GRID_RES)
    jc = int(round((90 - lat) / GRID_RES))
    ic = int(round((lon % 360) / GRID_RES))
    js = np.clip(np.arange(jc - n, jc + n + 1), 0, GRID_NLAT - 1)
    is_ = np.arange(ic - int(n * 1.4), ic + int(n * 1.4) + 1) % GRID_NLON
    lats = 90 - js * GRID_RES
    lons = lon + (np.arange(len(is_)) - int(n * 1.4)) * GRID_RES + (ic * GRID_RES - (lon % 360))

    def sub(name):
        return run.field(name, k)[np.ix_(js, is_)]

    u, v = sub("u10"), sub("v10")
    data = np.hypot(u, v) if var is None else sub(var)
    if layer == "precipitation":
        data = np.where(data < 0.05, np.nan, data)

    fig, ax = plt.subplots(figsize=(8, 6), dpi=110)
    mesh = ax.pcolormesh(lons, lats, data, cmap=cmap, shading="auto" if layer == "precipitation" else "gouraud",
                         vmin=0 if layer != "temperature" else None,
                         vmax=100 if layer == "clouds" else (10 if layer == "precipitation" else None))
    fig.colorbar(mesh, ax=ax, label=label, shrink=0.85)
    land = grids.landmask()
    if land is not None:
        ax.contour(lons, lats, land[np.ix_(js, is_)], levels=[0.5], colors="black", linewidths=0.8)
    step = max(1, len(is_) // 16)
    ax.quiver(lons[::step], lats[::step], u[::step, ::step], v[::step, ::step], alpha=0.55, width=0.002)
    for c in geo.largest_cities_in(lats.min(), lats.max(), lons.min(), lons.max(), limit=10):
        ax.plot(c["lon"], c["lat"], "k.", ms=3)
        ax.annotate(c["name"], (c["lon"], c["lat"]), fontsize=7, xytext=(3, 3), textcoords="offset points")
    ax.plot(lon, lat, marker="*", color="red", ms=14, mec="white")
    valid = run.times[k]
    ax.set_title(f"{label} — {valid:%Y-%m-%d %H:%M} UTC  ({model.upper()} {rid})", fontsize=10)
    ax.set_xlim(lons.min(), lons.max())
    ax.set_ylim(lats.min(), lats.max())
    ax.set_aspect(1 / np.cos(np.radians(lat)))
    ax.text(0.99, 0.01, "SkyMate", transform=ax.transAxes, ha="right", va="bottom", fontsize=8, alpha=0.6)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
