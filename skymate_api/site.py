"""Public website: pages, static assets and the keyless weather demo used by the home page."""
import os
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse

from . import forecast, security

STATIC = Path(__file__).parent / "static"
router = APIRouter(include_in_schema=False)
demo_limiter = security.SlidingWindow(20, 60)

BOT_USERNAME = os.environ.get("BOT_USERNAME", "skymatee_bot")


def _page(name: str) -> HTMLResponse:
    return HTMLResponse((STATIC / name).read_text(encoding="utf-8"), headers={"Cache-Control": "public, max-age=300"})


@router.get("/")
def home():
    return _page("home.html")


@router.get("/terms")
def terms():
    return _page("terms.html")


@router.get("/privacy")
def privacy():
    return _page("privacy.html")


@router.get("/robots.txt")
def robots():
    return HTMLResponse("User-agent: *\nAllow: /\nDisallow: /console-\nDisallow: /v1/\n", media_type="text/plain")


@router.get("/site/api/info")
def info():
    return {"bot": BOT_USERNAME, "premium_stars": int(os.environ.get("PREMIUM_STARS", "150"))}


def _demo(q: str) -> dict:
    loc = forecast.resolve_location(q)
    cur = forecast.current(loc)
    days = forecast.daily(loc, 5)["daily"]
    c, obs = cur["current"] or {}, cur.get("observed")
    return {
        "place": loc["name"], "country": loc.get("country", ""), "timezone": loc["timezone"],
        "temperature": obs["temperature"] if obs and obs.get("temperature") is not None else c.get("temperature"),
        "feels_like": c.get("feels_like"), "humidity": (obs or {}).get("humidity") or c.get("humidity"),
        "wind_speed": (obs or {}).get("wind_speed") or c.get("wind_speed"),
        "description": c.get("description") or (obs or {}).get("weather") or "",
        "condition": c.get("condition"), "is_day": c.get("is_day", True),
        "measured": {"station": obs["station"]["name"], "distance_km": obs["station"]["distance_km"],
                     "age_minutes": obs["age_minutes"]} if obs else None,
        "days": [{"date": d["date"], "min": d["temp_min"], "max": d["temp_max"], "condition": d["condition"],
                  "description": d["description"]} for d in days],
    }


@router.get("/site/api/weather")
async def demo_weather(request: Request, q: str = Query(..., min_length=1, max_length=100)):
    if not demo_limiter.allow(security.client_ip(request)):
        return JSONResponse({"error": "Too many searches. Try again in a minute."}, status_code=429)
    try:
        return await run_in_threadpool(_demo, q.strip())
    except forecast.NotFound:
        return JSONResponse({"error": "We couldn't find that place."}, status_code=404)
    except forecast.NoData:
        return JSONResponse({"error": "Weather data is updating. Try again shortly."}, status_code=503)
