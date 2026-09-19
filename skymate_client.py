"""Small client for the SkyMate Weather API (used by the bot and the desktop app)."""
import os

import requests

from skymate_api.config import API_PORT, load_env

load_env()


class SkyMateError(Exception):
    def __init__(self, status: int, message: str, suggestions=None):
        super().__init__(message)
        self.status, self.message, self.suggestions = status, message, suggestions or []


class SkyMate:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout: float = 30):
        self.base = (base_url or os.environ.get("SKYMATE_API_URL") or f"http://127.0.0.1:{API_PORT}").rstrip("/")
        self.key = api_key or os.environ.get("SKYMATE_API_KEY", "")
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers["X-API-Key"] = self.key

    def _get(self, path: str, raw: bool = False, **params):
        params = {k: v for k, v in params.items() if v is not None}
        try:
            r = self.s.get(self.base + path, params=params, timeout=self.timeout)
        except requests.RequestException as e:
            raise SkyMateError(0, f"SkyMate API unreachable: {e}")
        if r.status_code != 200:
            try:
                err = r.json()["error"]
                raise SkyMateError(r.status_code, err["message"], err.get("suggestions"))
            except (ValueError, KeyError):
                raise SkyMateError(r.status_code, r.text[:200])
        return r.content if raw else r.json()

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

    def status(self):
        return self._get("/v1/status")
