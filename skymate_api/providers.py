"""Last-resort live providers, used only when no stored SkyMate grid covers a request.

Responses are cached in SQLite; if a provider is unreachable, the most recent cached copy is served.
"""
import json
import logging
import time
from datetime import datetime, timezone

import numpy as np
import requests

from . import db
from .config import ENABLE_LIVE_FALLBACK, OPENWEATHER_KEY

log = logging.getLogger("skymate.providers")
FRESH_SECONDS = 1800


class Series:
    """Time series of model variables at one point (same shape as grids.Run.point output)."""

    def __init__(self, times, data, model, run, source):
        self.times, self.data, self.model, self.run, self.source = times, data, model, run, source


def _cached_json(key: str, url: str, params: dict):
    conn = db.connect()
    row = conn.execute("SELECT payload, fetched_at FROM point_cache WHERE cache_key=?", (key,)).fetchone()
    if row and time.time() - row["fetched_at"] < FRESH_SECONDS:
        return json.loads(row["payload"])
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        payload = r.json()
        with db.tx() as c:
            c.execute("INSERT OR REPLACE INTO point_cache VALUES (?,?,?)", (key, json.dumps(payload), time.time()))
        db.mark_source(key.split(":")[0], True)
        return payload
    except Exception as e:
        db.mark_source(key.split(":")[0], False, str(e))
        if row:
            log.warning("%s unreachable, serving cached copy: %s", key, e)
            return json.loads(row["payload"])
        raise


def _uv(speed, deg):
    rad = np.radians(np.asarray(deg, dtype=float))
    s = np.asarray(speed, dtype=float)
    return -s * np.sin(rad), -s * np.cos(rad)


def open_meteo(lat: float, lon: float) -> Series:
    p = _cached_json(
        f"open-meteo:{lat:.2f},{lon:.2f}", "https://api.open-meteo.com/v1/forecast",
        {"latitude": lat, "longitude": lon, "forecast_days": 10, "wind_speed_unit": "ms", "timezone": "GMT",
         "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,wind_gusts_10m,"
                   "pressure_msl,cloud_cover,precipitation,visibility,cape"})
    h = p["hourly"]
    times = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc) for t in h["time"]]
    arr = lambda k: np.array([np.nan if v is None else v for v in h[k]], dtype=float)
    u, v = _uv(arr("wind_speed_10m"), arr("wind_direction_10m"))
    data = {"t2m": arr("temperature_2m"), "rh": arr("relative_humidity_2m"), "u10": u, "v10": v,
            "gust": arr("wind_gusts_10m"), "msl": arr("pressure_msl"), "tcc": arr("cloud_cover"),
            "prate": arr("precipitation"), "vis": arr("visibility"), "cape": arr("cape")}
    return Series(times, data, "open-meteo", times[0], "live:open-meteo")


def openweather(lat: float, lon: float) -> Series:
    if not OPENWEATHER_KEY:
        raise RuntimeError("no OpenWeather key")
    p = _cached_json(f"openweather:{lat:.2f},{lon:.2f}", "https://api.openweathermap.org/data/2.5/forecast",
                     {"lat": lat, "lon": lon, "appid": OPENWEATHER_KEY, "units": "metric"})
    items = p["list"]
    times = [datetime.fromtimestamp(i["dt"], tz=timezone.utc) for i in items]
    g = lambda f: np.array([f(i) for i in items], dtype=float)
    u, v = _uv(g(lambda i: i["wind"]["speed"]), g(lambda i: i["wind"].get("deg", 0)))
    data = {"t2m": g(lambda i: i["main"]["temp"]), "rh": g(lambda i: i["main"]["humidity"]), "u10": u, "v10": v,
            "gust": g(lambda i: i["wind"].get("gust", np.nan)),
            "msl": g(lambda i: i["main"].get("sea_level", i["main"]["pressure"])),
            "tcc": g(lambda i: i["clouds"]["all"]),
            "prate": g(lambda i: (i.get("rain", {}).get("3h", 0) + i.get("snow", {}).get("3h", 0)) / 3),
            "vis": g(lambda i: i.get("visibility", np.nan)), "cape": np.full(len(items), np.nan)}
    return Series(times, data, "openweather", times[0], "live:openweather")


def live_series(lat: float, lon: float) -> Series | None:
    if not ENABLE_LIVE_FALLBACK:
        return None
    for provider in (open_meteo, openweather):
        try:
            return provider(lat, lon)
        except Exception as e:
            log.warning("Live provider %s failed: %s", provider.__name__, e)
    return None


def air_quality(lat: float, lon: float) -> dict | None:
    if not ENABLE_LIVE_FALLBACK:
        return None
    try:
        p = _cached_json(f"open-meteo-aq:{lat:.2f},{lon:.2f}",
                         "https://air-quality-api.open-meteo.com/v1/air-quality",
                         {"latitude": lat, "longitude": lon,
                          "current": "european_aqi,us_aqi,pm2_5,pm10,nitrogen_dioxide,sulphur_dioxide,carbon_monoxide,ozone"})
        c = p["current"]
        return {"european_aqi": c.get("european_aqi"), "us_aqi": c.get("us_aqi"),
                "components": {"pm2_5": c.get("pm2_5"), "pm10": c.get("pm10"), "no2": c.get("nitrogen_dioxide"),
                               "so2": c.get("sulphur_dioxide"), "co": c.get("carbon_monoxide"), "o3": c.get("ozone")},
                "source": "live:open-meteo"}
    except Exception as e:
        log.warning("AQ open-meteo failed: %s", e)
    if OPENWEATHER_KEY:
        try:
            p = _cached_json(f"openweather-aq:{lat:.2f},{lon:.2f}",
                             "http://api.openweathermap.org/data/2.5/air_pollution",
                             {"lat": lat, "lon": lon, "appid": OPENWEATHER_KEY})
            item = p["list"][0]
            comp = item["components"]
            return {"european_aqi": None, "us_aqi": None, "index_1_5": item["main"]["aqi"],
                    "components": {k: comp.get(k) for k in ("pm2_5", "pm10", "no2", "so2", "co", "o3")},
                    "source": "live:openweather"}
        except Exception as e:
            log.warning("AQ openweather failed: %s", e)
    return None


def history_archive(lat: float, lon: float, start: datetime, end: datetime) -> list[dict]:
    if not ENABLE_LIVE_FALLBACK:
        return []
    p = _cached_json(f"open-meteo-hist:{lat:.2f},{lon:.2f}:{start:%Y%m%d}:{end:%Y%m%d}",
                     "https://api.open-meteo.com/v1/forecast",
                     {"latitude": lat, "longitude": lon, "timezone": "GMT",
                      "start_date": start.strftime("%Y-%m-%d"), "end_date": end.strftime("%Y-%m-%d"),
                      "hourly": "temperature_2m,precipitation,cloud_cover"})
    h = p["hourly"]
    return [{"time": datetime.fromisoformat(t).replace(tzinfo=timezone.utc), "t2m": a, "prate": b, "tcc": c}
            for t, a, b, c in zip(h["time"], h["temperature_2m"], h["precipitation"], h["cloud_cover"])]
