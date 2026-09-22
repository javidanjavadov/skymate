"""Exact place names for a visitor's own position (e.g. "Ahmedli, Baku").

Names come from OpenStreetMap's Nominatim service and are stored permanently in SkyMate's database, one entry per
~100 m square, so each area is looked up only once. Follows the Nominatim usage policy: at most one request per
second from the whole service, an identifying User-Agent, permanent caching, attribution, and only for a visitor who
shared their location (never for search or autocomplete).

SKYMATE_REVERSE_URL points at another Nominatim-compatible server, or "" to turn this off. Without an answer, callers
fall back to SkyMate's own city list.
"""
import logging
import os
import threading
import time

import requests

from . import store

log = logging.getLogger("skymate.places")

URL = os.environ.get("SKYMATE_REVERSE_URL", "https://nominatim.openstreetmap.org/reverse")
USER_AGENT = "SkyMate/1.0 (+https://skymate-thfc.onrender.com)"
SCHEMA = ("CREATE TABLE IF NOT EXISTS place_names (cell TEXT PRIMARY KEY, name TEXT NOT NULL, country TEXT, "
          "detail TEXT, created_at TEXT)")

_rate_lock = threading.Lock()
_last_request = 0.0

# Only the neighbourhood is taken from the map service; the city name stays SkyMate's own.
PARTS = ("suburb", "quarter", "neighbourhood", "village", "hamlet", "city_district")


def init():
    with store.tx("api") as c:
        c.execute(SCHEMA)


def _cell(lat: float, lon: float) -> str:
    return f"{lat:.4f},{lon:.4f}"


def _neighbourhood(address: dict, city: str) -> str:
    def keep(value: str) -> bool:
        return bool(value) and "community board" not in value.lower() and value.lower() != city.lower()

    return next((address[k] for k in PARTS if keep(address.get(k, ""))), "")


def _fetch(lat: float, lon: float) -> dict | None:
    """One Nominatim request, never more than one per second across all threads."""
    global _last_request
    if not _rate_lock.acquire(timeout=1.5):
        return None  # busy: the caller shows the city name instead of waiting
    try:
        wait = 1.0 - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()
        r = requests.get(URL, timeout=4, headers={"User-Agent": USER_AGENT}, params={
            "format": "jsonv2", "lat": f"{lat:.4f}", "lon": f"{lon:.4f}", "zoom": 17, "addressdetails": 1,
            "accept-language": "en"})
        r.raise_for_status()
        return r.json().get("address") or {}
    except (requests.RequestException, ValueError) as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        log.warning("Place-name lookup failed (%s%s); using the city name", type(e).__name__, f" HTTP {status}" if status else "")
        return None
    finally:
        _rate_lock.release()


def lookup(lat: float, lon: float, city: str) -> dict | None:
    """Returns {"name", "country"} like {"Ahmedli, Baku"} for the ~100 m square, or None."""
    cell = f"{_cell(lat, lon)}|{city}"
    try:
        with store.tx("api") as c:
            row = c.execute("SELECT name, country, detail FROM place_names WHERE cell = ?", (cell,)).fetchone()
    except Exception:
        log.exception("Place-name cache unavailable")
        row = None
    if row:
        return {"name": row["name"], "country": row["country"], "detail": row["detail"] or ""} if row["name"] else None
    if not URL:
        return None
    address = _fetch(lat, lon)
    if address is None:
        return None  # temporary failure: not cached, try again next time
    # The street plus the city is exact; district names in OpenStreetMap often disagree with local usage, so they
    # are used only when no street is known.
    precise = address.get("road") or _neighbourhood(address, city)
    name = f"{precise}, {city}" if precise and city else ""
    detail = ""  # the street is already part of the name; a postcode adds nothing for weather
    country = (address.get("country_code") or "").upper()
    try:
        with store.tx("api") as c:
            # An empty name is cached too (open sea, desert), so the same square is never asked twice
            c.execute("INSERT INTO place_names(cell, name, country, detail, created_at) VALUES (?,?,?,?,?) "
                      "ON CONFLICT(cell) DO NOTHING", (cell, name, country, detail, store.now()))
    except Exception:
        log.exception("Could not cache place name")
    return {"name": name, "country": country, "detail": detail} if name else None
