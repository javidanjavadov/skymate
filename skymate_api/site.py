"""Public website: the single-page app, its data endpoints and SEO files.

The front end lives in /frontend (React + shadcn/ui + Magic UI) and is built into static/web.
"""
import math
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytz
from fastapi import APIRouter, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from . import forecast, geo, places, security

WEB = Path(__file__).parent / "static" / "web"
router = APIRouter(include_in_schema=False)
demo_limiter = security.SlidingWindow(30, 60)
places_limiter = security.SlidingWindow(90, 60)  # typing-as-you-search sends more, smaller requests

BOT_USERNAME = os.environ.get("BOT_USERNAME", "skymatee_bot")
APP_PAGES = ("/", "/terms", "/privacy")


def _index() -> HTMLResponse:
    index = WEB / "index.html"
    if not index.exists():
        return HTMLResponse("<h1>SkyMate</h1><p>Website build missing. Run <code>npm run build</code> in /frontend.</p>",
                            status_code=503)
    return HTMLResponse(index.read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})


for _path in APP_PAGES:
    router.add_api_route(_path, _index, methods=["GET"])


@router.get("/robots.txt")
def robots():
    return PlainTextResponse("User-agent: *\nAllow: /\nDisallow: /console-\nDisallow: /v1/\nDisallow: /site/\n")


@router.get("/site/api/info")
def info():
    return {"bot": BOT_USERNAME, "premium_stars": int(os.environ.get("PREMIUM_STARS", "150"))}


def _local_hour(iso: str, tz) -> datetime:
    return datetime.fromisoformat(iso).astimezone(tz)


HOUR_FIELDS = ("temperature", "feels_like", "condition", "description", "is_day", "precipitation_rate", "humidity",
               "dew_point", "visibility", "wind_speed", "wind_gust", "wind_direction", "uv_index", "cloud_cover")


def _mean(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 1) if values else None


def _mean_direction(degrees):
    degrees = [d for d in degrees if d is not None]
    if not degrees:
        return None
    x = sum(math.cos(math.radians(d)) for d in degrees)
    y = sum(math.sin(math.radians(d)) for d in degrees)
    return round(math.degrees(math.atan2(y, x)) % 360)


def _day_details(hourly: list[dict], tz) -> dict:
    """Per local day: values the 10-day cards need that the daily summary doesn't carry."""
    days = defaultdict(list)
    for h in hourly:
        days[_local_hour(h["time"], tz).date().isoformat()].append(h)
    out = {}
    for day, hs in days.items():
        feels = [h["feels_like"] for h in hs if h.get("feels_like") is not None]
        vis = [h["visibility"] for h in hs if h.get("visibility") is not None]
        out[day] = {"feels_like_max": max(feels) if feels else None, "humidity": _mean(h.get("humidity") for h in hs),
                    "dew_point": _mean(h.get("dew_point") for h in hs), "visibility_min": min(vis) if vis else None,
                    "wind_direction": _mean_direction(h.get("wind_direction") for h in hs)}
    return out


def _dashboard(q: str | None, lat: float | None, lon: float | None, precise: bool = False) -> dict:
    loc = forecast.resolve_location(q, lat, lon)
    source = "skymate"
    if precise and q is None and lat is not None and lon is not None:
        exact = places.lookup(lat, lon, loc["name"])  # the visitor's own position: name the neighbourhood, not just the city
        if exact:
            loc["name"], loc["country"], source = exact["name"], exact["country"] or loc.get("country", ""), "osm"
            loc["detail"] = exact.get("detail", "")
    cur = forecast.current(loc)
    hourly = forecast.hourly(loc, 240)["hourly"]
    daily = forecast.daily(loc, 10)["daily"]
    try:
        alerts = forecast.alerts(loc, 72)["alerts"]
    except forecast.NoData:
        alerts = []
    tz = pytz.timezone(loc["timezone"])
    now = datetime.now(timezone.utc)
    c = cur["current"] or {}
    obs = cur.get("observed")

    def measured(field):
        return obs.get(field) if obs and obs.get(field) is not None else c.get(field)

    # Precipitation: rates are mm/h at each step; integrate over the step length.
    def rain_between(start: datetime, end: datetime) -> float:
        total = 0.0
        for a, b in zip(hourly, hourly[1:]):
            ta, tb = datetime.fromisoformat(a["time"]), datetime.fromisoformat(b["time"])
            if tb <= start or ta >= end:
                continue
            hours = (min(tb, end) - max(ta, start)).total_seconds() / 3600
            total += max(0.0, a.get("precipitation_rate") or 0.0) * hours
        return round(total, 1)

    local_midnight = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    today = daily[0] if daily else {}
    protect_until = None
    for h in hourly:
        t = _local_hour(h["time"], tz)
        if t.date() == now.astimezone(tz).date() and (h.get("uv_index") or 0) >= 3:
            protect_until = t.isoformat()

    # A real measurement beats the model: keep "now", the first hourly slot and today's range consistent with it.
    shown_now = measured("temperature")
    hourly_out = [{"time": h["time"], **{f: h.get(f) for f in HOUR_FIELDS}}
                  for h in hourly if datetime.fromisoformat(h["time"]) >= now - timedelta(hours=2)][:12]
    details = _day_details(hourly, tz)
    daily_out = [{"date": d["date"], "min": d["temp_min"], "max": d["temp_max"], "condition": d["condition"],
                  "description": d["description"], "precipitation": d["precipitation_sum"], "uv_max": d.get("uv_max"),
                  "wind_max": d.get("wind_max"), "gust_max": d.get("gust_max"), "sunrise": d.get("sunrise"),
                  "sunset": d.get("sunset"), **details.get(d["date"], {})} for d in daily]
    if shown_now is not None:
        if hourly_out:
            hourly_out[0]["temperature"] = shown_now
        if daily_out:
            if daily_out[0]["max"] is None or shown_now > daily_out[0]["max"]:
                daily_out[0]["max"] = shown_now
            if daily_out[0]["min"] is None or shown_now < daily_out[0]["min"]:
                daily_out[0]["min"] = shown_now

    return {
        "location": {"name": loc["name"], "country": loc.get("country", ""), "timezone": loc["timezone"],
                     "lat": loc["lat"], "lon": loc["lon"], "name_source": source, "detail": loc.get("detail", "")},
        "now": {
            "temperature": measured("temperature"),
            "feels_like": c.get("feels_like"),
            "humidity": measured("humidity"),
            "dew_point": measured("dew_point"),
            "pressure": measured("pressure"),
            "wind_speed": measured("wind_speed"),
            "wind_gust": measured("wind_gust"),
            "wind_direction": measured("wind_direction"),
            "visibility": measured("visibility"),
            "cloud_cover": c.get("cloud_cover"),
            "condition": c.get("condition") or "Clouds",
            "description": c.get("description") or (obs or {}).get("weather") or "",
            "is_day": c.get("is_day", True),
            "uv_index": c.get("uv_index"),
        },
        "measured": {"station": obs["station"]["name"], "distance_km": obs["station"]["distance_km"],
                     "age_minutes": obs["age_minutes"], "time": obs["time"]} if obs else None,
        "sun": cur.get("sun", {}),
        "precipitation": {"today_mm": rain_between(local_midnight.astimezone(timezone.utc), now),
                          "next_24h_mm": rain_between(now, now + timedelta(hours=24))},
        "uv": {"now": c.get("uv_index"), "max_today": today.get("uv_max"), "protect_until": protect_until},
        "hourly": hourly_out,
        "daily": daily_out,
        "alerts": [{"event": a["event"], "severity": a["severity"], "start": a["start"], "end": a["end"]}
                   for a in alerts[:3]],
        "meta": {"source": cur["meta"].get("source"), "data_age_hours": cur["meta"].get("data_age_hours")},
    }


@router.get("/site/api/weather")
async def site_weather(request: Request, q: str | None = Query(None, min_length=1, max_length=100),
                       lat: float | None = Query(None, ge=-90, le=90), lon: float | None = Query(None, ge=-180, le=180),
                       precise: bool = False):
    """precise=1 only for the visitor's own shared position: names the neighbourhood (OpenStreetMap, cached)."""
    if not demo_limiter.allow(security.client_ip(request)):
        return JSONResponse({"error": "Too many searches. Wait a minute, then try again."}, status_code=429)
    if not q and (lat is None or lon is None):
        return JSONResponse({"error": "Enter a city name."}, status_code=400)
    try:
        return await run_in_threadpool(_dashboard, q.strip() if q else None, lat, lon, precise)
    except forecast.NotFound:
        return JSONResponse({"error": "That place wasn't found. Check the spelling or add the country, e.g. “Paris, FR”."},
                            status_code=404)
    except forecast.NoData:
        return JSONResponse({"error": "Weather data is updating. Try again in a few minutes."}, status_code=503)


@router.get("/site/api/places")
async def site_places(request: Request, q: str = Query(..., min_length=1, max_length=100)):
    if not places_limiter.allow(security.client_ip(request)):
        return JSONResponse({"error": "Too many searches. Wait a minute, then try again."}, status_code=429)
    places = await run_in_threadpool(geo.suggest, q, 6)
    return {"places": [{"name": p["name"], "country": p["country"], "lat": p["lat"], "lon": p["lon"]} for p in places]}
