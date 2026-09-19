import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from fastapi.responses import HTMLResponse, JSONResponse, Response

from . import __version__, admin_panel, auth, db, forecast, geo, hosting, maps, observations, scheduler, store
from .config import ADMIN_TOKEN

log = logging.getLogger("skymate.server")

DESCRIPTION = """
Global weather API: real station measurements (live and decades of history), current conditions,
hourly and 10-day forecasts, alerts, UV, air quality and maps.

Measured values (`observed`, `/v1/observations/*`) come from real instruments; forecast values are model estimates.

Authenticate with your key in the **`X-API-Key`** header (or `api_key` query parameter).

Locate a place with **`q`** (e.g. `Baku` or `Paris, FR`) or with **`lat`** and **`lon`**.
Use `units=metric` (°C, m/s, mm, m) or `units=imperial` (°F, mph, in, mi).

Every response includes `meta` with the data source, model run and data age.
""" + forecast.ATTRIBUTION

app = FastAPI(title="SkyMate Weather API", version=__version__, description=DESCRIPTION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])
app.include_router(admin_panel.router)
app.include_router(hosting.router)


@app.on_event("startup")
async def _startup():
    db.init()
    store.init("bot")
    try:
        await run_in_threadpool(geo.ensure_loaded)
    except Exception:
        log.exception("City database could not be loaded; geocoding unavailable until next start")
    scheduler.start()
    hosting.start_keepalive()
    try:
        await hosting.start_bot()
    except Exception:
        log.exception("Telegram bot failed to start")


@app.on_event("shutdown")
async def _shutdown():
    await hosting.stop_bot()


# ─── Errors ──────────────────────────────────────────────────────────────────

def _err(status: int, code: str, message: str, headers=None, **extra):
    return JSONResponse({"error": {"code": code, "message": message, **extra}}, status_code=status, headers=headers)


@app.exception_handler(auth.AuthError)
async def _auth_error(_, e: auth.AuthError):
    code = {401: "unauthorized", 403: "plan_limit", 429: "rate_limited"}.get(e.status, "error")
    return _err(e.status, code, e.message, e.headers)


@app.exception_handler(forecast.NotFound)
async def _not_found(_, e: forecast.NotFound):
    return _err(404, "not_found", str(e), suggestions=e.suggestions)


@app.exception_handler(forecast.NoData)
async def _no_data(_, e: forecast.NoData):
    return _err(503, "no_data", str(e))


# ─── Auth dependency ─────────────────────────────────────────────────────────

def api_key(request: Request, x_api_key: str | None = Header(None), api_key: str | None = Query(None)):
    info, headers = auth.check(x_api_key or api_key, request.url.path)
    request.state.rl_headers = headers
    return info


@app.middleware("http")
async def _headers(request: Request, call_next):
    response = await call_next(request)
    for k, v in getattr(request.state, "rl_headers", {}).items():
        response.headers[k] = v
    return response


# ─── Units ───────────────────────────────────────────────────────────────────

_TEMP = {"temperature", "feels_like", "dew_point", "temp_min", "temp_max", "peak_temperature"}
_SPEED = {"wind_speed", "wind_gust", "wind_max", "gust_max", "peak_wind_gust"}
_RATE = {"precipitation_rate", "peak_precipitation_rate"}
_SUM = {"precipitation_sum", "precipitation"}


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


UNITS = {
    "metric": {"temperature": "°C", "speed": "m/s", "pressure": "hPa", "precipitation": "mm",
               "precipitation_rate": "mm/h", "visibility": "m"},
    "imperial": {"temperature": "°F", "speed": "mph", "pressure": "hPa", "precipitation": "in",
                 "precipitation_rate": "in/h", "visibility": "mi"},
}

Units = Literal["metric", "imperial"]
Model = Literal["gfs", "ecmwf"] | None


def _loc(q, lat, lon):
    return forecast.resolve_location(q, lat, lon)


def _respond(payload: dict, units: str):
    payload = _convert(payload, units)
    payload["units"] = UNITS[units]
    return payload


# ─── Public ──────────────────────────────────────────────────────────────────

HOME_PAGE = Path(__file__).parent / "static" / "home.html"


@app.get("/", include_in_schema=False, response_class=HTMLResponse)
def home():
    return HOME_PAGE.read_text(encoding="utf-8")


@app.get("/health", tags=["service"])
def health():
    return {"status": "ok", "version": __version__}


@app.get("/v1/status", tags=["service"])
async def status():
    """Data freshness per model and how far into the future stored data reaches (offline readiness)."""
    return await run_in_threadpool(forecast.status)


@app.get("/v1/me", tags=["service"])
def me(key=Depends(api_key)):
    """The calling key's plan and limits."""
    return {"name": key["name"], "plan": key["plan"], "limits": auth.PLANS.get(key["plan"], auth.PLANS["free"])}


@app.get("/v1/plans", tags=["service"])
def plans():
    return {"plans": auth.PLANS}


# ─── Weather ─────────────────────────────────────────────────────────────────

@app.get("/v1/geocode", tags=["location"])
async def geocode(q: str, limit: int = Query(5, ge=1, le=20), _=Depends(api_key)):
    return {"results": await run_in_threadpool(geo.search, q, limit)}


@app.get("/v1/reverse", tags=["location"])
async def reverse(lat: float, lon: float, _=Depends(api_key)):
    r = await run_in_threadpool(geo.reverse, lat, lon)
    if not r:
        raise forecast.NotFound("No populated place nearby")
    return r


@app.get("/v1/current", tags=["weather"])
async def current(q: str | None = None, lat: float | None = None, lon: float | None = None,
                  units: Units = "metric", model: Model = None, _=Depends(api_key)):
    def work():
        return forecast.current(_loc(q, lat, lon), model)
    return _respond(await run_in_threadpool(work), units)


@app.get("/v1/forecast/hourly", tags=["weather"])
async def forecast_hourly(q: str | None = None, lat: float | None = None, lon: float | None = None,
                          hours: int = Query(24, ge=3, le=240), units: Units = "metric", model: Model = None,
                          _=Depends(api_key)):
    def work():
        return forecast.hourly(_loc(q, lat, lon), hours, model)
    return _respond(await run_in_threadpool(work), units)


@app.get("/v1/forecast/daily", tags=["weather"])
async def forecast_daily(q: str | None = None, lat: float | None = None, lon: float | None = None,
                         days: int = Query(5, ge=1, le=10), units: Units = "metric", model: Model = None,
                         key=Depends(api_key)):
    auth.require(key, "max_forecast_days", days)

    def work():
        return forecast.daily(_loc(q, lat, lon), days, model)
    return _respond(await run_in_threadpool(work), units)


@app.get("/v1/alerts", tags=["weather"])
async def alerts(q: str | None = None, lat: float | None = None, lon: float | None = None,
                 hours: int = Query(72, ge=6, le=240), units: Units = "metric", _=Depends(api_key)):
    def work():
        return forecast.alerts(_loc(q, lat, lon), hours)
    return _respond(await run_in_threadpool(work), units)


@app.get("/v1/uv", tags=["weather"])
async def uv(q: str | None = None, lat: float | None = None, lon: float | None = None, _=Depends(api_key)):
    return await run_in_threadpool(lambda: forecast.uv(_loc(q, lat, lon)))


@app.get("/v1/air-quality", tags=["weather"])
async def air_quality(q: str | None = None, lat: float | None = None, lon: float | None = None,
                      _=Depends(api_key)):
    return await run_in_threadpool(lambda: forecast.air_quality(_loc(q, lat, lon)))


@app.get("/v1/history", tags=["weather"])
async def history(q: str | None = None, lat: float | None = None, lon: float | None = None,
                  days: int = Query(7, ge=1, le=90), units: Units = "metric", key=Depends(api_key)):
    auth.require(key, "max_history_days", days)
    return _respond(await run_in_threadpool(lambda: forecast.history(_loc(q, lat, lon), days)), units)


# ─── Measurements ────────────────────────────────────────────────────────────

@app.get("/v1/observations/latest", tags=["measurements"])
async def observations_latest(q: str | None = None, lat: float | None = None, lon: float | None = None,
                              radius_km: float = Query(50, ge=1, le=300), limit: int = Query(5, ge=1, le=50),
                              max_age_hours: float = Query(3, ge=0.5, le=48), units: Units = "metric",
                              _=Depends(api_key)):
    """Latest real measurements from stations near a place (airports and national weather stations)."""
    def work():
        loc = _loc(q, lat, lon)
        return {"location": loc,
                "stations": observations.nearby(loc["lat"], loc["lon"], radius_km, limit, max_age_hours),
                "meta": {"source": "measured", "attribution": forecast.OBS_ATTRIBUTION}}
    return _respond(await run_in_threadpool(work), units)


@app.get("/v1/observations/history", tags=["measurements"])
async def observations_history(station: str | None = None, q: str | None = None, lat: float | None = None,
                               lon: float | None = None, start: str | None = None, end: str | None = None,
                               days: int = Query(7, ge=1, le=366), units: Units = "metric", key=Depends(api_key)):
    """Measured readings for one station. Pass `station` (ICAO like UBBB or WMO like 37864),
    or a place to use the nearest station with data. `start`/`end` are ISO dates (default: last `days`)."""
    def work():
        end_t = datetime.fromisoformat(end).replace(tzinfo=timezone.utc) if end else datetime.now(timezone.utc)
        start_t = datetime.fromisoformat(start).replace(tzinfo=timezone.utc) if start else end_t - timedelta(days=days)
        if (end_t - start_t).days > 366:
            raise forecast.NotFound("Maximum range is 366 days per request")
        if (datetime.now(timezone.utc) - start_t).days > auth.PLANS[key["plan"]]["max_history_days"]:
            auth.require(key, "max_history_days", (datetime.now(timezone.utc) - start_t).days)
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
            raise forecast.NotFound(f"Station '{sid}' not found")
        return {"station": st, "coverage": observations.coverage(sid),
                "observations": observations.history(sid, start_t, end_t),
                "meta": {"source": "measured", "attribution": forecast.OBS_ATTRIBUTION}}
    return _respond(await run_in_threadpool(work), units)


@app.get("/v1/stations", tags=["measurements"])
async def stations(q: str | None = None, lat: float | None = None, lon: float | None = None,
                   radius_km: float = Query(100, ge=1, le=500), _=Depends(api_key)):
    def work():
        loc = _loc(q, lat, lon)
        out = observations.stations_near(loc["lat"], loc["lon"], radius_km, 50)
        for s in out:
            s["coverage"] = observations.coverage(s["id"])
        return {"location": loc, "stations": out}
    return await run_in_threadpool(work)


@app.get("/v1/map.png", tags=["maps"], response_class=Response)
async def map_png(q: str | None = None, lat: float | None = None, lon: float | None = None,
                  layer: Literal["temperature", "precipitation", "wind", "clouds"] = "temperature",
                  radius: float = Query(6.0, ge=1, le=30), _=Depends(api_key)):
    def work():
        loc = _loc(q, lat, lon)
        return maps.render(loc["lat"], loc["lon"], layer, radius)
    try:
        png = await run_in_threadpool(work)
    except LookupError as e:
        raise forecast.NoData(str(e))
    return Response(png, media_type="image/png", headers={"Cache-Control": "public, max-age=600"})


# ─── Admin (for billing/customer management) ─────────────────────────────────

def admin(x_admin_token: str | None = Header(None)):
    if not ADMIN_TOKEN or not x_admin_token or not secrets.compare_digest(x_admin_token, ADMIN_TOKEN):
        raise auth.AuthError(401, "Admin token required.")


@app.get("/admin/keys", tags=["admin"], dependencies=[Depends(admin)])
def admin_keys():
    return {"keys": auth.list_keys()}


@app.post("/admin/keys", tags=["admin"], dependencies=[Depends(admin)])
def admin_create_key(name: str, plan: str = "free"):
    try:
        return {"api_key": auth.create_key(name, plan), "note": "Store this key now; it cannot be shown again."}
    except ValueError as e:
        return _err(400, "bad_request", str(e))


@app.post("/admin/keys/{key_id}/revoke", tags=["admin"], dependencies=[Depends(admin)])
def admin_revoke(key_id: int):
    auth.set_active(key_id, False)
    return {"revoked": key_id}


@app.post("/admin/keys/{key_id}/plan", tags=["admin"], dependencies=[Depends(admin)])
def admin_plan(key_id: int, plan: str):
    try:
        auth.set_plan(key_id, plan)
    except ValueError as e:
        return _err(400, "bad_request", str(e))
    return {"key_id": key_id, "plan": plan}


@app.post("/admin/keys/by-name/{name}/plan", tags=["admin"], dependencies=[Depends(admin)])
def admin_plan_by_name(name: str, plan: str):
    ids = [k["id"] for k in auth.list_keys() if k["name"] == name and k["active"]]
    for key_id in ids:
        auth.set_plan(key_id, plan)
    return {"updated": ids, "plan": plan}


@app.post("/admin/keys/by-name/{name}/revoke", tags=["admin"], dependencies=[Depends(admin)])
def admin_revoke_by_name(name: str):
    ids = [k["id"] for k in auth.list_keys() if k["name"] == name and k["active"]]
    for key_id in ids:
        auth.set_active(key_id, False)
    return {"revoked": ids}


@app.get("/admin/usage", tags=["admin"], dependencies=[Depends(admin)])
def admin_usage(days: int = 30):
    return {"usage": auth.usage(days)}
