"""SkyMate Weather API (FastAPI application)."""
import logging
import re
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__, admin_panel, auth, db, forecast, geo, hosting, maps, observations, scheduler, security, site, store

log = logging.getLogger("skymate.server")
STATIC = Path(__file__).parent / "static"

DESCRIPTION = """
Global weather data: real station measurements (live and historical), current conditions,
hourly and 10-day forecasts, weather warnings, UV index, air quality and maps.

**Authentication.** Send your key in the `X-API-Key` header. Keys are never accepted in the URL.

**Locations.** Use `q` (for example `Baku` or `Paris, FR`) or both `lat` and `lon`.

**Units.** `units=metric` (°C, m/s, mm, m) or `units=imperial` (°F, mph, in, mi).

**Data provenance.** Measured values (`observed`, `/v1/observations/*`) come from physical instruments.
Forecast values are model estimates. Every response carries `meta` with its source and age.

**Errors.** All errors use `{"error": {"code", "message", "request_id"}}`. Quote the `request_id` to support.

**Limits.** Per-minute and daily quotas depend on your plan (`/v1/plans`); remaining quota is returned in
`X-RateLimit-Remaining-Day`.

""" + forecast.ATTRIBUTION

TAGS = [
    {"name": "weather", "description": "Forecasts, warnings, UV and air quality."},
    {"name": "measurements", "description": "Real observations from airport and national weather stations."},
    {"name": "location", "description": "Place search and reverse geocoding."},
    {"name": "maps", "description": "Weather map images."},
    {"name": "service", "description": "Account, plans and service status."},
]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init()
    store.init("bot")
    security.init_audit()
    try:
        await run_in_threadpool(geo.ensure_loaded)
    except Exception:
        log.exception("City database could not be loaded; geocoding unavailable until next start")
    scheduler.start()
    hosting.start_keepalive()
    if store.IS_PG:
        threading.Thread(target=_database_selftest, name="skymate-selftest", daemon=True).start()
    try:
        await hosting.start_bot()
    except Exception:
        log.exception("Telegram bot failed to start")
    yield
    await hosting.stop_bot()


def _database_selftest():
    """Runs scripts/db_smoke_test.py on startup so database dialect bugs surface in the log immediately."""
    import runpy
    try:
        runpy.run_path(str(Path(__file__).resolve().parent.parent / "scripts" / "db_smoke_test.py"), run_name="__main__")
    except Exception:
        log.exception("DATABASE SELF-TEST FAILED")


app = FastAPI(title="SkyMate Weather API", version=__version__, description=DESCRIPTION, openapi_tags=TAGS,
              lifespan=lifespan, redoc_url="/redoc", docs_url="/docs",
              swagger_ui_parameters={"defaultModelsExpandDepth": -1})
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"],
                   allow_headers=["X-API-Key", "Content-Type", "X-Request-ID"],
                   expose_headers=["X-Request-ID", "X-RateLimit-Remaining-Day", "X-Plan"], max_age=3600)
app.include_router(site.router)
app.include_router(admin_panel.router)
app.include_router(hosting.router)
(STATIC / "web" / "app").mkdir(parents=True, exist_ok=True)
app.mount("/app", StaticFiles(directory=STATIC / "web" / "app"), name="web-assets")


@app.get("/favicon.svg", include_in_schema=False)
def favicon():
    return FileResponse(STATIC / "web" / "favicon.svg", media_type="image/svg+xml",
                        headers={"Cache-Control": "public, max-age=86400"})


# ─── Middleware: request id, public rate limit, security headers ─────────────

_PUBLIC_PATHS = ("/", "/terms", "/privacy", "/v1/status", "/v1/plans", "/docs", "/redoc", "/openapi.json")


@app.middleware("http")
async def _security(request: Request, call_next):
    security.new_request_id(request)
    if request.url.path in _PUBLIC_PATHS and not security.public_limiter.allow(security.client_ip(request)):
        response = _err(request, 429, "rate_limited", "Too many requests. Slow down.", {"Retry-After": "60"})
    else:
        response = await call_next(request)
    for k, v in getattr(request.state, "rl_headers", {}).items():
        response.headers[k] = v
    security.apply_headers(request, response)
    return response


# ─── Errors ──────────────────────────────────────────────────────────────────

def _err(request: Request, status: int, code: str, message: str, headers=None, **extra):
    body = {"error": {"code": code, "message": message, "request_id": getattr(request.state, "request_id", ""), **extra}}
    return JSONResponse(body, status_code=status, headers=headers)


@app.exception_handler(auth.AuthError)
async def _auth_error(request: Request, e: auth.AuthError):
    code = {400: "bad_request", 401: "unauthorized", 403: "plan_limit", 429: "rate_limited"}.get(e.status, "error")
    return _err(request, e.status, code, e.message, e.headers)


@app.exception_handler(forecast.NotFound)
async def _not_found(request: Request, e: forecast.NotFound):
    return _err(request, 404, "not_found", str(e), suggestions=e.suggestions)


@app.exception_handler(forecast.NoData)
async def _no_data(request: Request, e: forecast.NoData):
    return _err(request, 503, "no_data", str(e), {"Retry-After": "300"})


@app.exception_handler(RequestValidationError)
async def _validation(request: Request, e: RequestValidationError):
    problems = [f"{'.'.join(str(p) for p in err['loc'][1:]) or 'request'}: {err['msg']}" for err in e.errors()][:5]
    return _err(request, 422, "invalid_request", "; ".join(problems))


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, e: StarletteHTTPException):
    if e.status_code == 404:
        return _err(request, 404, "not_found", "Not found.")
    if e.status_code == 405:
        return _err(request, 405, "method_not_allowed", "Method not allowed.")
    return _err(request, e.status_code, "error", "Request failed.")


@app.exception_handler(Exception)
async def _unexpected(request: Request, e: Exception):
    log.exception("Unhandled error on %s (request %s)", request.url.path, getattr(request.state, "request_id", ""))
    return _err(request, 500, "internal_error", "Something went wrong on our side. Please try again later.")


# ─── Authentication ──────────────────────────────────────────────────────────

def api_key(request: Request, x_api_key: str | None = Header(None, description="Your SkyMate API key")):
    ip = security.client_ip(request)
    try:
        info, headers = auth.check(x_api_key, request.url.path)
    except auth.AuthError as e:
        if e.status == 401 and not security.invalid_key_limiter.allow(ip):
            raise auth.AuthError(429, "Too many invalid API keys from your address. Try again later.",
                                 {"Retry-After": "300"})
        raise
    request.state.rl_headers = headers
    return info


# ─── Parameters ──────────────────────────────────────────────────────────────

Units = Literal["metric", "imperial"]
Model = Literal["gfs", "ecmwf"] | None
Q = Query(None, min_length=1, max_length=100, description="Place name, e.g. `Baku` or `Paris, FR`")
LAT = Query(None, ge=-90, le=90, description="Latitude")
LON = Query(None, ge=-180, le=180, description="Longitude")


def _loc(q, lat, lon):
    if not q and (lat is None or lon is None):
        raise auth.AuthError(400, "Provide either q, or both lat and lon.")
    return forecast.resolve_location(q.strip() if q else None, lat, lon)


_TEMP = {"temperature", "feels_like", "dew_point", "temp_min", "temp_max", "peak_temperature"}
_SPEED = {"wind_speed", "wind_gust", "wind_max", "gust_max", "peak_wind_gust"}
_RATE = {"precipitation_rate", "peak_precipitation_rate"}
_SUM = {"precipitation_sum", "precipitation"}

UNITS = {
    "metric": {"temperature": "°C", "speed": "m/s", "pressure": "hPa", "precipitation": "mm",
               "precipitation_rate": "mm/h", "visibility": "m"},
    "imperial": {"temperature": "°F", "speed": "mph", "pressure": "hPa", "precipitation": "in",
                 "precipitation_rate": "in/h", "visibility": "mi"},
}


def _convert(obj, units: str):
    if units != "imperial":
        return obj
    if isinstance(obj, list):
        return [_convert(x, units) for x in obj]
    if not isinstance(obj, dict):
        return obj
    out = {}
    for k, v in obj.items():
        if k == "peak" and isinstance(v, (int, float)) and obj.get("peak_field"):
            k2 = "peak_" + obj["peak_field"]
            out[k] = _convert({k2: v}, units)[k2]
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            if k in _TEMP:
                v = round(v * 9 / 5 + 32, 1)
            elif k in _SPEED:
                v = round(v * 2.23694, 1)
            elif k in _RATE or k in _SUM:
                v = round(v / 25.4, 3)
            elif k == "visibility":
                v = round(v / 1609.34, 2)
            out[k] = v
        else:
            out[k] = _convert(v, units)
    return out


def _respond(payload: dict, units: str):
    payload = _convert(payload, units)
    payload["units"] = UNITS[units]
    return payload


def _date(value: str | None, name: str) -> datetime | None:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(value)
    except ValueError:
        raise auth.AuthError(400, f"{name} must be an ISO date like 2024-01-31.")
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ─── Service ─────────────────────────────────────────────────────────────────

@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}


@app.get("/v1/status", tags=["service"], summary="Service and data freshness")
async def status():
    return await run_in_threadpool(forecast.status)


@app.get("/v1/plans", tags=["service"], summary="Available plans")
def plans():
    public = {k: v for k, v in auth.PLANS.items() if k in ("free", "starter", "pro", "business")}
    return {"plans": public}


@app.get("/v1/me", tags=["service"], summary="Your plan and limits")
def me(key=Depends(api_key)):
    return {"name": key["name"], "plan": key["plan"], "limits": auth.PLANS.get(key["plan"], auth.PLANS["free"])}


# ─── Location ────────────────────────────────────────────────────────────────

@app.get("/v1/geocode", tags=["location"], summary="Search places")
async def geocode(q: str = Query(..., min_length=1, max_length=100), limit: int = Query(5, ge=1, le=20),
                  _=Depends(api_key)):
    return {"results": await run_in_threadpool(geo.search, q.strip(), limit)}


@app.get("/v1/reverse", tags=["location"], summary="Nearest place to coordinates")
async def reverse(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180),
                  _=Depends(api_key)):
    r = await run_in_threadpool(geo.reverse, lat, lon)
    if not r:
        raise forecast.NotFound("No populated place nearby")
    return r


# ─── Weather ─────────────────────────────────────────────────────────────────

@app.get("/v1/current", tags=["weather"], summary="Current conditions")
async def current(q: str | None = Q, lat: float | None = LAT, lon: float | None = LON,
                  units: Units = "metric", model: Model = None, _=Depends(api_key)):
    return _respond(await run_in_threadpool(lambda: forecast.current(_loc(q, lat, lon), model)), units)


@app.get("/v1/forecast/hourly", tags=["weather"], summary="Hourly forecast")
async def forecast_hourly(q: str | None = Q, lat: float | None = LAT, lon: float | None = LON,
                          hours: int = Query(24, ge=3, le=240), units: Units = "metric", model: Model = None,
                          _=Depends(api_key)):
    return _respond(await run_in_threadpool(lambda: forecast.hourly(_loc(q, lat, lon), hours, model)), units)


@app.get("/v1/forecast/daily", tags=["weather"], summary="Daily forecast")
async def forecast_daily(q: str | None = Q, lat: float | None = LAT, lon: float | None = LON,
                         days: int = Query(5, ge=1, le=10), units: Units = "metric", model: Model = None,
                         key=Depends(api_key)):
    auth.require(key, "max_forecast_days", days)
    return _respond(await run_in_threadpool(lambda: forecast.daily(_loc(q, lat, lon), days, model)), units)


@app.get("/v1/alerts", tags=["weather"], summary="Weather warnings")
async def alerts(q: str | None = Q, lat: float | None = LAT, lon: float | None = LON,
                 hours: int = Query(72, ge=6, le=240), units: Units = "metric", _=Depends(api_key)):
    return _respond(await run_in_threadpool(lambda: forecast.alerts(_loc(q, lat, lon), hours)), units)


@app.get("/v1/uv", tags=["weather"], summary="UV index")
async def uv(q: str | None = Q, lat: float | None = LAT, lon: float | None = LON, _=Depends(api_key)):
    return await run_in_threadpool(lambda: forecast.uv(_loc(q, lat, lon)))


@app.get("/v1/air-quality", tags=["weather"], summary="Air quality")
async def air_quality(q: str | None = Q, lat: float | None = LAT, lon: float | None = LON, _=Depends(api_key)):
    return await run_in_threadpool(lambda: forecast.air_quality(_loc(q, lat, lon)))


@app.get("/v1/history", tags=["weather"], summary="Modelled history (when no station is nearby)")
async def history(q: str | None = Q, lat: float | None = LAT, lon: float | None = LON,
                  days: int = Query(7, ge=1, le=90), units: Units = "metric", key=Depends(api_key)):
    auth.require(key, "max_history_days", days)
    return _respond(await run_in_threadpool(lambda: forecast.history(_loc(q, lat, lon), days)), units)


# ─── Measurements ────────────────────────────────────────────────────────────

STATION_ID = re.compile(r"^(isd:)?[A-Za-z0-9]{3,12}$")


@app.get("/v1/observations/latest", tags=["measurements"], summary="Latest measurements near a place")
async def observations_latest(q: str | None = Q, lat: float | None = LAT, lon: float | None = LON,
                              radius_km: float = Query(50, ge=1, le=300), limit: int = Query(5, ge=1, le=50),
                              max_age_hours: float = Query(3, ge=0.5, le=48), units: Units = "metric",
                              _=Depends(api_key)):
    def work():
        loc = _loc(q, lat, lon)
        return {"location": loc,
                "stations": observations.nearby(loc["lat"], loc["lon"], radius_km, limit, max_age_hours),
                "meta": {"source": "measured", "attribution": forecast.OBS_ATTRIBUTION}}
    return _respond(await run_in_threadpool(work), units)


@app.get("/v1/observations/history", tags=["measurements"], summary="Measured history for a station")
async def observations_history(station: str | None = Query(None, description="ICAO (e.g. UBBB) or WMO (e.g. 37864)"),
                               q: str | None = Q, lat: float | None = LAT, lon: float | None = LON,
                               start: str | None = Query(None, max_length=32), end: str | None = Query(None, max_length=32),
                               days: int = Query(7, ge=1, le=366), units: Units = "metric", key=Depends(api_key)):
    if station and not STATION_ID.match(station):
        raise auth.AuthError(400, "station must be an ICAO or WMO identifier.")
    end_t = _date(end, "end") or datetime.now(timezone.utc)
    start_t = _date(start, "start") or end_t - timedelta(days=days)
    if start_t >= end_t:
        raise auth.AuthError(400, "start must be before end.")
    if (end_t - start_t).days > 366:
        raise auth.AuthError(400, "The maximum range is 366 days per request.")
    auth.require(key, "max_history_days", max(0, (datetime.now(timezone.utc) - start_t).days))

    def work():
        sid = station
        if not sid:
            loc = _loc(q, lat, lon)
            best = None
            for s in observations.stations_near(loc["lat"], loc["lon"], 60, 10):
                n = len(observations.history(s["id"], start_t, end_t, limit=5000))
                if n and (best is None or n > best[1]):
                    best = (s["id"], n)
            if not best:
                raise forecast.NotFound("No measuring station with data near this location")
            sid = best[0]
        st = observations.station(sid)
        if not st:
            raise forecast.NotFound("Station not found")
        return {"station": st, "coverage": observations.coverage(sid),
                "observations": observations.history(sid, start_t, end_t),
                "meta": {"source": "measured", "attribution": forecast.OBS_ATTRIBUTION}}
    return _respond(await run_in_threadpool(work), units)


@app.get("/v1/stations", tags=["measurements"], summary="Measuring stations near a place")
async def stations(q: str | None = Q, lat: float | None = LAT, lon: float | None = LON,
                   radius_km: float = Query(100, ge=1, le=500), _=Depends(api_key)):
    def work():
        loc = _loc(q, lat, lon)
        out = observations.stations_near(loc["lat"], loc["lon"], radius_km, 50)
        for s in out:
            s["coverage"] = observations.coverage(s["id"])
        return {"location": loc, "stations": out}
    return await run_in_threadpool(work)


# ─── Maps ────────────────────────────────────────────────────────────────────

@app.get("/v1/map.png", tags=["maps"], summary="Weather map image", response_class=Response,
         responses={200: {"content": {"image/png": {}}}})
async def map_png(q: str | None = Q, lat: float | None = LAT, lon: float | None = LON,
                  layer: Literal["temperature", "precipitation", "wind", "clouds"] = "temperature",
                  radius: float = Query(6.0, ge=1, le=30), _=Depends(api_key)):
    def work():
        loc = _loc(q, lat, lon)
        return maps.render(loc["lat"], loc["lon"], layer, radius)
    try:
        png = await run_in_threadpool(work)
    except LookupError as e:
        raise forecast.NoData(str(e))
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=600"})
