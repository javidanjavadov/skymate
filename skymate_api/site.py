"""Public website: the single-page app, its data endpoints and SEO files.

The front end lives in /frontend (React + shadcn/ui + Magic UI) and is built into static/web.
"""
import math
import os
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from html import escape
from pathlib import Path as FilePath

import pytz
from fastapi import APIRouter, HTTPException, Path, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from . import db, forecast, geo, lastknown, places, security

WEB = FilePath(__file__).parent / "static" / "web"
router = APIRouter(include_in_schema=False)
demo_limiter = security.SlidingWindow(30, 60)
places_limiter = security.SlidingWindow(90, 60)  # typing-as-you-search sends more, smaller requests

BOT_USERNAME = os.environ.get("BOT_USERNAME", "skymatee_bot")
APP_PAGES = ("/", "/terms", "/privacy")


# ── Page wording per language ────────────────────────────────────────────────
# The app itself translates everything once it starts; these are the tags a crawler or chat app reads first.
PAGE_TEXT = {
    "en": {
        "home_title": "SkyMate — Weather You Can Trust",
        "home_description": ("Live weather from real station measurements: the nearest station reading, hourly and "
                             "10-day forecasts, severe-weather warnings, UV and wind. Free on the web, in Telegram "
                             "and via API."),
        "city_title": "{city} Weather — Live Measurements and 10-Day Forecast | SkyMate",
        "city_description": ("Current weather in {where} from the nearest real weather station, plus hourly and "
                             "10-day forecasts, warnings, UV and wind. Free, no sign-up."),
        "city_heading": "Weather in {where}",
        "noscript": "SkyMate needs JavaScript to show live weather. You can also use the Telegram bot @{bot}.",
    },
    "az": {
        "home_title": "SkyMate — Etibar edə biləcəyiniz hava",
        "home_description": ("Real stansiya ölçmələri ilə canlı hava: ən yaxın stansiyanın göstəricisi, saatlıq və "
                             "10 günlük proqnoz, təhlükəli hava xəbərdarlıqları, UV və külək. Saytda, Telegram-da "
                             "və API ilə pulsuz."),
        "city_title": "{city} hava — canlı ölçmələr və 10 günlük proqnoz | SkyMate",
        "city_description": ("{where} üçün ən yaxın real meteostansiyadan indiki hava, saatlıq və 10 günlük proqnoz, "
                             "xəbərdarlıqlar, UV və külək. Pulsuz, qeydiyyatsız."),
        "city_heading": "{where} üçün hava",
        "noscript": "Canlı havanı göstərmək üçün SkyMate-ə JavaScript lazımdır. Telegram botundan da istifadə edə bilərsiniz: @{bot}.",
    },
    "ru": {
        "home_title": "SkyMate — погода, которой можно доверять",
        "home_description": ("Погода по реальным измерениям станций: показание ближайшей станции, почасовой и "
                             "10-дневный прогноз, предупреждения о непогоде, УФ и ветер. Бесплатно на сайте, "
                             "в Telegram и через API."),
        "city_title": "Погода в {city} — реальные измерения и прогноз на 10 дней | SkyMate",
        "city_description": ("Текущая погода в {where} с ближайшей реальной метеостанции, почасовой и 10-дневный "
                             "прогноз, предупреждения, УФ и ветер. Бесплатно, без регистрации."),
        "city_heading": "Погода в {where}",
        "noscript": "Для показа погоды SkyMate нужен JavaScript. Также можно использовать Telegram-бот @{bot}.",
    },
}


def _language(request: Request) -> str:
    """First supported language from the browser's Accept-Language header."""
    header = (request.headers.get("accept-language") or "").lower()
    for part in header.split(","):
        code = part.split(";")[0].strip()[:2]
        if code in PAGE_TEXT:
            return code
    return "en"


def _index(request: Request) -> HTMLResponse:
    index = WEB / "index.html"
    if not index.exists():
        return HTMLResponse("<h1>SkyMate</h1><p>Website build missing. Run <code>npm run build</code> in /frontend.</p>",
                            status_code=503)
    text = PAGE_TEXT[_language(request)]
    return _with_tags(index.read_text(encoding="utf-8"), text["home_title"], text["home_description"],
                      f"{PUBLIC_URL}/", "", _language(request), text["noscript"].format(bot=BOT_USERNAME), "no-cache")


for _path in APP_PAGES:
    router.add_api_route(_path, _index, methods=["GET"])


@router.get("/robots.txt")
def robots():
    return PlainTextResponse("User-agent: *\nAllow: /\nDisallow: /console-\nDisallow: /v1/\nDisallow: /site/\n"
                             f"Sitemap: {PUBLIC_URL}/sitemap.xml\n")


CITY_LIMIT = 200
PUBLIC_URL = (os.environ.get("PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL")
              or "https://skymate-thfc.onrender.com").rstrip("/")


def _slug(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name.translate(geo._TRANSLIT)).encode("ascii", "ignore").decode()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", plain.lower())).strip("-")


@lru_cache(maxsize=1)
def _sitemap_cities() -> list[dict]:
    """Cities worth their own page: every larger place in Azerbaijan, then the biggest elsewhere."""
    conn = db.connect()
    rows = conn.execute("SELECT name, country, lat, lon, population FROM cities WHERE country = 'AZ' "
                        "ORDER BY population DESC LIMIT 60").fetchall()
    rows += conn.execute("SELECT name, country, lat, lon, population FROM cities WHERE country <> 'AZ' "
                         "ORDER BY population DESC LIMIT ?", (CITY_LIMIT - 60,)).fetchall()
    seen, out = set(), []
    for r in rows:
        slug = _slug(r["name"])
        if slug and slug not in seen:
            seen.add(slug)
            out.append({"slug": slug, "name": r["name"], "country": r["country"]})
    return out


@lru_cache(maxsize=512)
def _city_for(slug: str) -> dict | None:
    for city in _sitemap_cities():
        if city["slug"] == slug:
            return city
    hits = geo.search(slug.replace("-", " "), limit=1)
    return {"slug": slug, "name": hits[0]["name"], "country": hits[0]["country"]} if hits else None


def _with_tags(html: str, title: str, description: str, url: str, heading: str, language: str, noscript: str,
               cache: str) -> HTMLResponse:
    """The same single-page app, with the tags search engines and chat apps read."""
    html = re.sub(r"<title>.*?</title>", f"<title>{escape(title)}</title>", html, count=1)
    html = re.sub(r'(<meta name="description" content=")[^"]*(")', lambda m: m.group(1) + escape(description) + m.group(2), html, count=1)
    html = re.sub(r'(<meta property="og:title" content=")[^"]*(")', lambda m: m.group(1) + escape(title) + m.group(2), html, count=1)
    html = re.sub(r'(<meta property="og:description" content=")[^"]*(")', lambda m: m.group(1) + escape(description) + m.group(2), html, count=1)
    html = re.sub(r'(<meta property="og:url" content=")[^"]*(")', lambda m: m.group(1) + escape(url) + m.group(2), html, count=1)
    html = re.sub(r'(<link rel="canonical" href=")[^"]*(")', lambda m: m.group(1) + escape(url) + m.group(2), html, count=1)
    html = re.sub(r'<html lang="[a-z-]+"', f'<html lang="{language}"', html, count=1)
    html = re.sub(r"<noscript>.*?</noscript>", f"<noscript>{f'<h1>{escape(heading)}</h1>' if heading else ''}"
                  f"{escape(noscript)}</noscript>", html, count=1, flags=re.S)
    return HTMLResponse(html, headers={"Cache-Control": cache})


@router.get("/weather/{slug}")
def city_page(request: Request, slug: str = Path(..., min_length=1, max_length=60, pattern=r"^[a-z0-9-]+$")):
    city = _city_for(slug)
    if not city:
        raise HTTPException(status_code=404)
    index = WEB / "index.html"
    if not index.exists():
        return _index(request)
    where = f"{city['name']}, {city['country']}" if city["country"] else city["name"]
    language = _language(request)
    text = PAGE_TEXT[language]
    return _with_tags(index.read_text(encoding="utf-8"),
                      text["city_title"].format(city=city["name"], where=where),
                      text["city_description"].format(city=city["name"], where=where),
                      f"{PUBLIC_URL}/weather/{slug}", text["city_heading"].format(where=where), language,
                      text["noscript"].format(bot=BOT_USERNAME), "public, max-age=600")


@router.get("/sitemap.xml")
def sitemap():
    pages = ["", "/terms", "/privacy"] + [f"/weather/{c['slug']}" for c in _sitemap_cities()]
    urls = "".join(f"<url><loc>{PUBLIC_URL}{p}</loc><changefreq>hourly</changefreq>"
                   f"<priority>{'1.0' if not p else '0.8' if p.startswith('/weather/') else '0.3'}</priority></url>"
                   for p in pages)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    return Response(xml, media_type="application/xml", headers={"Cache-Control": "public, max-age=86400"})



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
                     "age_minutes": obs["age_minutes"], "time": obs["time"],
                     # What the forecast model said for the same moment, so visitors can judge it themselves
                     "model_temperature": c.get("temperature"),
                     "station_temperature": obs.get("temperature")} if obs else None,
        "sun": cur.get("sun", {}),
        "precipitation": {"today_mm": rain_between(local_midnight.astimezone(timezone.utc), now),
                          "next_24h_mm": rain_between(now, now + timedelta(hours=24))},
        "uv": {"now": c.get("uv_index"), "max_today": today.get("uv_max"), "protect_until": protect_until},
        "hourly": hourly_out,
        "daily": daily_out,
        "alerts": [{"event": a["event"], "severity": a["severity"], "start": a["start"], "end": a["end"]}
                   for a in alerts[:3]],
        "meta": {"source": cur["meta"].get("source"), "data_age_hours": cur["meta"].get("data_age_hours"),
                 "model": cur["meta"].get("model"), "run": cur["meta"].get("run")},
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
        place = lastknown.key(q, lat, lon)
        dashboard = await run_in_threadpool(_dashboard, q.strip() if q else None, lat, lon, precise)
        await run_in_threadpool(lastknown.save, place, dashboard)
        return dashboard
    except forecast.NotFound:
        return JSONResponse({"error": "That place wasn't found. Check the spelling or add the country, e.g. “Paris, FR”."},
                            status_code=404)
    except forecast.NoData:
        # Forecast files are still loading (they are rebuilt after every restart): serve the last good answer
        stored = await run_in_threadpool(lastknown.load, lastknown.key(q, lat, lon))
        if stored:
            return stored
        return JSONResponse({"error": "Weather data is updating. Try again in a few minutes."}, status_code=503)


@router.get("/site/api/places")
async def site_places(request: Request, q: str = Query(..., min_length=1, max_length=100)):
    if not places_limiter.allow(security.client_ip(request)):
        return JSONResponse({"error": "Too many searches. Wait a minute, then try again."}, status_code=429)
    places = await run_in_threadpool(geo.suggest, q, 6)
    return {"places": [{"name": p["name"], "country": p["country"], "lat": p["lat"], "lon": p["lon"]} for p in places]}
