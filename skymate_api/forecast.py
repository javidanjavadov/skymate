"""Builds API responses from stored grids (primary) or live providers (fallback)."""
import math
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import numpy as np
import pytz

from . import geo, grids, observations, physics, providers
from .config import MODELS

STALE_HOURS = 18
ATTRIBUTION = ("Forecast data derived from NOAA GFS (public domain) and ECMWF open data (CC-BY-4.0). "
               "Place names from GeoNames (CC-BY 4.0).")
OBS_ATTRIBUTION = ("Measurements from airport (METAR) and national weather service (WMO SYNOP) stations, "
                   "via NOAA and Ogimet; historical records from NOAA ISD.")


class NotFound(Exception):
    def __init__(self, message, suggestions=None):
        super().__init__(message)
        self.suggestions = suggestions or []


class NoData(Exception):
    pass


# ─── Location ────────────────────────────────────────────────────────────────

def resolve_location(q: str | None = None, lat: float | None = None, lon: float | None = None) -> dict:
    if q:
        hits = geo.search(q, limit=5)
        if not hits:
            raise NotFound(f"Location '{q}' not found")
        loc = dict(hits[0])
    elif lat is not None and lon is not None:
        if not (-90 <= lat <= 90 and -180 <= lon <= 360):
            raise NotFound("Coordinates out of range")
        near = geo.reverse(lat, lon)
        loc = {"name": near["name"] if near and near["distance_km"] < 30 else f"{lat:.2f}, {lon:.2f}",
               "country": near["country"] if near else "", "lat": lat, "lon": lon,
               # A nearby town's zone from GeoNames beats the offline boundary lookup, which gets some
               # countries wrong (it answers Asia/Dubai everywhere in Azerbaijan).
               "timezone": near["timezone"] if near and near["distance_km"] < 100 else None}
    else:
        raise NotFound("Provide either q or lat and lon")
    loc["lon"] = ((loc["lon"] + 180) % 360) - 180
    loc["timezone"] = loc.get("timezone") or geo.timezone_at(loc["lat"], loc["lon"])
    offset = pytz.timezone(loc["timezone"]).utcoffset(datetime.utcnow())
    loc["utc_offset_seconds"] = int(offset.total_seconds())
    loc.pop("population", None)
    return loc


# ─── Data selection ──────────────────────────────────────────────────────────

@lru_cache(maxsize=2048)
def _grid_point(model: str, rid: str, lat: float, lon: float):
    run = grids.open_run(model, rid)
    return providers.Series(run.times, run.point(lat, lon), model, run.run, "skymate")


def series_for(lat: float, lon: float, model: str | None = None) -> providers.Series:
    """Freshest stored run that still covers 'now'; falls back to live providers."""
    now = datetime.now(timezone.utc)
    candidates = []
    for m in ([model] if model else MODELS):
        for rid in grids.complete_runs(m):
            run_t = grids.parse_run(rid)
            run = grids.open_run(m, rid)
            if run.times[0] <= now + timedelta(hours=1) and run.times[-1] >= now:
                candidates.append((run_t, -MODELS.index(m) if m in MODELS else 0, m, rid))
                break
    if candidates:
        _, _, m, rid = max(candidates)
        return _grid_point(m, rid, round(lat, 2), round(lon, 2))
    live = providers.live_series(lat, lon)
    if live:
        return live
    raise NoData("No forecast data available for this location right now")


def meta(s: providers.Series) -> dict:
    age = (datetime.now(timezone.utc) - s.run).total_seconds() / 3600
    attribution = ATTRIBUTION if s.source == "skymate" else f"Temporary live data from {s.model}."
    return {"source": s.source, "model": s.model, "run": s.run.isoformat(),
            "data_age_hours": round(age, 1), "stale": s.source == "skymate" and age > STALE_HOURS,
            "attribution": attribution}


def _f(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 2)


def _state(lat, lon, t: datetime, d: dict) -> dict:
    t2m, rh = d["t2m"], d["rh"]
    u, v = d["u10"], d["v10"]
    wind = math.hypot(u, v) if not (math.isnan(u) or math.isnan(v)) else float("nan")
    main, desc = physics.condition(t2m, d["prate"], d["tcc"], None if math.isnan(d["vis"]) else d["vis"],
                                   None if math.isnan(d["cape"]) else d["cape"])
    cloud = 0 if math.isnan(d["tcc"]) else d["tcc"]
    return {
        "time": t.isoformat(),
        "temperature": _f(t2m),
        "feels_like": _f(physics.feels_like(t2m, rh, wind)) if not (math.isnan(rh) or math.isnan(wind)) else _f(t2m),
        "humidity": _f(rh),
        "dew_point": _f(physics.dewpoint(t2m, rh)) if not math.isnan(rh) else None,
        "pressure": _f(d["msl"]),
        "wind_speed": _f(wind),
        "wind_gust": _f(d["gust"]),
        "wind_direction": _f(physics.wind_dir(u, v)) if not math.isnan(wind) else None,
        "cloud_cover": _f(d["tcc"]),
        "precipitation_rate": _f(max(0.0, d["prate"])) if not math.isnan(d["prate"]) else None,
        "visibility": _f(d["vis"]),
        "cape": _f(d["cape"]),
        "condition": main,
        "description": desc,
        "is_day": physics.is_day(lat, lon, t),
        "uv_index": physics.uv_index(lat, lon, t, cloud),
    }


def _at(s: providers.Series, t: datetime) -> dict:
    times = s.times
    if t <= times[0]:
        return {k: float(v[0]) for k, v in s.data.items()}
    for k in range(len(times) - 1):
        if times[k] <= t <= times[k + 1]:
            w = (t - times[k]).total_seconds() / (times[k + 1] - times[k]).total_seconds()
            return {n: float(a[k] * (1 - w) + a[k + 1] * w) for n, a in s.data.items()}
    return {k: float(v[-1]) for k, v in s.data.items()}


def _sun(loc: dict, day_local: datetime):
    tz = pytz.timezone(loc["timezone"])
    rise, sset = physics.sun_times(loc["lat"], loc["lon"], day_local)
    iso = lambda x: x.replace(microsecond=0).astimezone(tz).isoformat() if x else None
    return {"sunrise": iso(rise), "sunset": iso(sset)}


# ─── Public builders ─────────────────────────────────────────────────────────

OBS_RADIUS_KM = 40
OBS_MAX_AGE_HOURS = 3


def observed(loc: dict) -> dict | None:
    """Nearest real measurement, if a station is close enough and reported recently."""
    try:
        hits = observations.nearby(loc["lat"], loc["lon"], OBS_RADIUS_KM, 1, OBS_MAX_AGE_HOURS)
    except Exception:
        return None
    if not hits:
        return None
    h = hits[0]
    return {**h["observation"], "station": h["station"]}


def current(loc: dict, model=None) -> dict:
    """Model estimate for the exact location, plus the nearest real measurement when one exists."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    obs = observed(loc)
    try:
        s = series_for(loc["lat"], loc["lon"], model)
    except NoData:
        if not obs:
            raise
        return {"location": loc, "current": None, "observed": obs,
                "sun": _sun(loc, now.astimezone(pytz.timezone(loc["timezone"]))),
                "meta": {"source": "measured", "attribution": OBS_ATTRIBUTION}}
    state = _state(loc["lat"], loc["lon"], now, _at(s, now))
    local_today = now.astimezone(pytz.timezone(loc["timezone"]))
    return {"location": loc, "current": state, "observed": obs, "sun": _sun(loc, local_today), "meta": meta(s)}


def hourly(loc: dict, hours: int = 24, model=None) -> dict:
    s = series_for(loc["lat"], loc["lon"], model)
    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=hours)
    items = []
    for k, t in enumerate(s.times):
        if now - timedelta(hours=1.5) <= t <= end:
            items.append(_state(loc["lat"], loc["lon"], t, {n: float(a[k]) for n, a in s.data.items()}))
    return {"location": loc, "hourly": items, "meta": meta(s)}


def _severity(main: str) -> int:
    return {"Thunderstorm": 6, "Snow": 5, "Rain": 4, "Drizzle": 3, "Fog": 2, "Mist": 1}.get(main, 0)


def daily(loc: dict, days: int = 5, model=None) -> dict:
    s = series_for(loc["lat"], loc["lon"], model)
    tz = pytz.timezone(loc["timezone"])
    today = datetime.now(tz).date()
    buckets: dict = {}
    for k, t in enumerate(s.times):
        d = t.astimezone(tz).date()
        if d < today:
            continue
        dt_h = ((s.times[k + 1] - t).total_seconds() / 3600) if k + 1 < len(s.times) else 3
        buckets.setdefault(d, []).append((t, {n: float(a[k]) for n, a in s.data.items()}, dt_h))
    out = []
    for d in sorted(buckets)[:days]:
        rows = buckets[d]
        temps = [r[1]["t2m"] for r in rows if not math.isnan(r[1]["t2m"])]
        precip = sum(max(0.0, r[1]["prate"]) * r[2] for r in rows if not math.isnan(r[1]["prate"]))
        winds = [math.hypot(r[1]["u10"], r[1]["v10"]) for r in rows]
        gusts = [r[1]["gust"] for r in rows if not math.isnan(r[1]["gust"])]
        states = [_state(loc["lat"], loc["lon"], r[0], r[1]) for r in rows]
        noon = min(states, key=lambda x: abs(datetime.fromisoformat(x["time"]).astimezone(tz).hour - 13))
        worst = max(states, key=lambda x: _severity(x["condition"]))
        pick = worst if precip >= 1 and _severity(worst["condition"]) >= 3 else noon
        day_start = tz.localize(datetime(d.year, d.month, d.day))
        out.append({
            "date": d.isoformat(),
            "temp_min": _f(min(temps)) if temps else None,
            "temp_max": _f(max(temps)) if temps else None,
            "precipitation_sum": _f(precip),
            "wind_max": _f(max(winds)) if winds else None,
            "gust_max": _f(max(gusts)) if gusts else None,
            "uv_max": max(x["uv_index"] for x in states),
            "condition": pick["condition"],
            "description": pick["description"],
            **_sun(loc, day_start),
            "complete": len(rows) >= (8 if s.model in ("gfs", "openweather") else 4),
        })
    return {"location": loc, "daily": out, "meta": meta(s)}


ALERT_RULES = [
    # (id, severity, test on a state dict, headline)
    ("extreme_heat", "severe", lambda x: (x["temperature"] or -99) >= 40, "Extreme heat"),
    ("heat", "moderate", lambda x: 35 <= (x["temperature"] or -99) < 40, "High temperatures"),
    ("extreme_cold", "severe", lambda x: (x["temperature"] or 99) <= -20, "Extreme cold"),
    ("frost", "minor", lambda x: -20 < (x["temperature"] or 99) <= 0, "Frost"),
    ("storm_wind", "severe", lambda x: (x["wind_gust"] or 0) >= 25, "Storm-force wind gusts"),
    ("strong_wind", "moderate", lambda x: 17 <= (x["wind_gust"] or 0) < 25, "Strong wind gusts"),
    ("heavy_rain", "moderate", lambda x: (x["precipitation_rate"] or 0) >= 7.6 and x["condition"] != "Snow",
     "Heavy rain"),
    ("heavy_snow", "moderate", lambda x: x["condition"] == "Snow" and (x["precipitation_rate"] or 0) >= 2.5,
     "Heavy snow"),
    ("thunderstorm", "moderate", lambda x: x["condition"] == "Thunderstorm", "Thunderstorms"),
    ("fog", "minor", lambda x: x["condition"] == "Fog", "Dense fog"),
]


def alerts(loc: dict, hours: int = 72, model=None) -> dict:
    """SkyMate's own alerts, computed by applying threshold rules to the forecast."""
    h = hourly(loc, hours, model)
    found = []
    for rule_id, severity, test, headline in ALERT_RULES:
        hits = [x for x in h["hourly"] if test(x)]
        if not hits:
            continue
        peak_key = {"extreme_heat": "temperature", "heat": "temperature", "extreme_cold": "temperature",
                    "frost": "temperature", "storm_wind": "wind_gust", "strong_wind": "wind_gust",
                    "heavy_rain": "precipitation_rate", "heavy_snow": "precipitation_rate"}.get(rule_id)
        peak = None
        if peak_key:
            vals = [x[peak_key] for x in hits if x[peak_key] is not None]
            peak = (min(vals) if "cold" in rule_id or rule_id == "frost" else max(vals)) if vals else None
        found.append({"id": rule_id, "severity": severity, "event": headline,
                      "start": hits[0]["time"], "end": hits[-1]["time"], "peak": peak, "peak_field": peak_key})
    order = {"severe": 0, "moderate": 1, "minor": 2}
    found.sort(key=lambda a: (order[a["severity"]], a["start"]))
    return {"location": loc, "alerts": found, "meta": h["meta"]}


def uv(loc: dict, model=None) -> dict:
    c = current(loc, model)
    if c["current"] is None:
        raise NoData("UV estimate needs forecast data, which is unavailable right now")
    d = daily(loc, 1, model)
    uv_now = c["current"]["uv_index"]
    uv_max = max(uv_now, d["daily"][0]["uv_max"]) if d["daily"] else uv_now
    return {"location": loc, "uv_index": uv_now, "uv_max_today": uv_max,
            "category": _uv_cat(uv_now), "method": "estimated from solar angle and forecast cloud cover",
            "meta": c["meta"]}


def _uv_cat(v: float) -> str:
    return "low" if v < 3 else "moderate" if v < 6 else "high" if v < 8 else "very_high" if v < 11 else "extreme"


def history(loc: dict, days: int = 7) -> dict:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    rows = grids.history_point(loc["lat"], loc["lon"], start, end)
    source = "skymate"
    expected = days * 8
    if len(rows) < expected * 0.6:
        try:
            rows = providers.history_archive(loc["lat"], loc["lon"], start, end)
            source = "live:open-meteo"
        except Exception:
            pass
    items = [{"time": r["time"].isoformat(), "temperature": _f(r["t2m"]),
              "precipitation_rate": _f(r["prate"]), "cloud_cover": _f(r["tcc"])} for r in rows]
    return {"location": loc, "history": items,
            "meta": {"source": source, "points": len(items),
                     "attribution": ATTRIBUTION if source == "skymate" else "Temporary live data from open-meteo."}}


def air_quality(loc: dict) -> dict:
    aq = providers.air_quality(loc["lat"], loc["lon"])
    if not aq:
        raise NoData("Air quality data is currently unavailable")
    return {"location": loc, "air_quality": aq,
            "meta": {"source": aq["source"], "note": "Air quality comes from a live partner source, not SkyMate grids."}}


def status() -> dict:
    now = datetime.now(timezone.utc)
    models = {}
    for m in MODELS:
        runs = grids.complete_runs(m)
        if runs:
            run = grids.open_run(m, runs[0])
            models[m] = {"latest_run": run.run.isoformat(),
                         "age_hours": round((now - run.run).total_seconds() / 3600, 1),
                         "covers_until": run.times[-1].isoformat(), "runs_stored": len(runs)}
        else:
            models[m] = {"latest_run": None}
    hist = sorted(p.stem for p in grids.HISTORY_DIR.glob("*.npz") if ".tmp" not in p.name)
    try:
        obs = observations.stats()
    except Exception:
        obs = None
    return {"models": models, "observations": obs,
            "history": {"slices": len(hist), "from": hist[0] if hist else None, "to": hist[-1] if hist else None},
            "offline_ready_until": max((v["covers_until"] for v in models.values() if v.get("covers_until")),
                                       default=None)}
