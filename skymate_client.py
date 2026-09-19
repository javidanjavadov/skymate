"""Small client for the SkyMate Weather API (used by the bot and the desktop app)."""
import hashlib
import os
from urllib.parse import quote

import requests

DEFAULT_URL = "http://127.0.0.1:8000"


class SkyMateError(Exception):
    def __init__(self, status: int, message: str, suggestions=None):
        super().__init__(message)
        self.status, self.message, self.suggestions = status, message, suggestions or []


class SkyMate:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout: float = 30):
        self.timeout = timeout
        self.s = requests.Session()
        self.configure(base_url or os.environ.get("SKYMATE_API_URL") or DEFAULT_URL,
                       api_key if api_key is not None else os.environ.get("SKYMATE_API_KEY", ""))

    def configure(self, base_url: str, api_key: str):
        self.base = base_url.rstrip("/")
        self.key = api_key
        self.s.headers["X-API-Key"] = api_key

    def _request(self, method: str, path: str, raw: bool = False, headers=None, **params):
        params = {k: v for k, v in params.items() if v is not None}
        try:
            r = self.s.request(method, self.base + path, params=params, headers=headers, timeout=self.timeout)
        except requests.RequestException as e:
            raise SkyMateError(0, f"SkyMate API unreachable: {e}")
        if r.status_code != 200:
            try:
                err = r.json()["error"]
            except (ValueError, KeyError, TypeError):
                raise SkyMateError(r.status_code, r.text[:200])
            raise SkyMateError(r.status_code, err["message"], err.get("suggestions"))
        return r.content if raw else r.json()

    def _get(self, path: str, raw: bool = False, **params):
        return self._request("GET", path, raw=raw, **params)

    def me(self):
        return self._get("/v1/me")

    def geocode(self, q, limit=5):
        return self._get("/v1/geocode", q=q, limit=limit)["results"]

    def reverse(self, lat, lon):
        return self._get("/v1/reverse", lat=lat, lon=lon)

    def current(self, q=None, lat=None, lon=None, units="metric"):
        return self._get("/v1/current", q=q, lat=lat, lon=lon, units=units)

    def hourly(self, q=None, lat=None, lon=None, hours=24, units="metric"):
        return self._get("/v1/forecast/hourly", q=q, lat=lat, lon=lon, hours=hours, units=units)

    def daily(self, q=None, lat=None, lon=None, days=5, units="metric"):
        return self._get("/v1/forecast/daily", q=q, lat=lat, lon=lon, days=days, units=units)

    def alerts(self, q=None, lat=None, lon=None, units="metric"):
        return self._get("/v1/alerts", q=q, lat=lat, lon=lon, units=units)

    def uv(self, q=None, lat=None, lon=None):
        return self._get("/v1/uv", q=q, lat=lat, lon=lon)

    def air_quality(self, q=None, lat=None, lon=None):
        return self._get("/v1/air-quality", q=q, lat=lat, lon=lon)

    def history(self, q=None, lat=None, lon=None, days=7, units="metric"):
        return self._get("/v1/history", q=q, lat=lat, lon=lon, days=days, units=units)

    def map_png(self, q=None, lat=None, lon=None, layer="temperature", radius=6):
        return self._get("/v1/map.png", raw=True, q=q, lat=lat, lon=lon, layer=layer, radius=radius)

    def observations_latest(self, q=None, lat=None, lon=None, radius_km=50, limit=5, units="metric"):
        return self._get("/v1/observations/latest", q=q, lat=lat, lon=lon, radius_km=radius_km, limit=limit,
                         units=units)

    def observation_history(self, station=None, q=None, lat=None, lon=None, days=7, start=None, end=None,
                            units="metric"):
        return self._get("/v1/observations/history", station=station, q=q, lat=lat, lon=lon, days=days,
                         start=start, end=end, units=units)

    def stations(self, q=None, lat=None, lon=None, radius_km=100):
        return self._get("/v1/stations", q=q, lat=lat, lon=lon, radius_km=radius_km)

    def status(self):
        return self._get("/v1/status")


def admin_prefix(token: str) -> str:
    """Secret URL prefix of the admin panel; must match skymate_api.security.admin_prefix."""
    return "/console-" + hashlib.sha256(f"skymate-admin-path:{token}".encode()).hexdigest()[:24]


class SkyMateAdmin(SkyMate):
    """Key management through the hidden admin API (needs SKYMATE_ADMIN_TOKEN)."""

    def __init__(self, base_url=None, admin_token=None, timeout=30):
        super().__init__(base_url, "", timeout)
        token = admin_token or os.environ.get("SKYMATE_ADMIN_TOKEN", "")
        self.admin = {"X-Admin-Token": token}
        self.prefix = admin_prefix(token) + "/api"

    def create_key(self, name: str, plan: str) -> str:
        return self._request("POST", f"{self.prefix}/keys", headers=self.admin, name=name, plan=plan)["api_key"]

    def set_plan_by_name(self, name: str, plan: str):
        return self._request("POST", f"{self.prefix}/keys/by-name/{quote(name, safe='')}/plan",
                             headers=self.admin, plan=plan)

    def revoke_by_name(self, name: str):
        return self._request("POST", f"{self.prefix}/keys/by-name/{quote(name, safe='')}/revoke", headers=self.admin)
