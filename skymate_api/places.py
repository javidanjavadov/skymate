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
          "created_at TEXT)")

_rate_lock = threading.Lock()
_last_request = 0.0

SMALL = ("neighbourhood", "suburb", "quarter", "city_district", "village", "hamlet")
BIG = ("city", "town", "municipality", "village", "county")


def init():
    with store.tx("api") as c:
        c.execute(SCHEMA)


def _cell(lat: float, lon: float) -> str:
    return f"{lat:.3f},{lon:.3f}"


def _label(address: dict) -> str:
    big = next((address[k] for k in BIG if address.get(k)), "")
    small = next((address[k] for k in SMALL if address.get(k) and address[k] != big), "")
    return f"{small}, {big}" if small and big else big or small


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
            "format": "jsonv2", "lat": f"{lat:.3f}", "lon": f"{lon:.3f}", "zoom": 16, "addressdetails": 1,
            "accept-language": "en"})
        r.raise_for_status()
        return r.json().get("address") or {}
    except (requests.RequestException, ValueError):
        log.warning("Place-name lookup failed; using the city name")
        return None
    finally:
        _rate_lock.release()


def lookup(lat: float, lon: float) -> dict | None:
    """Returns {"name", "country"} for the ~100 m square around the point, or None."""
    cell = _cell(lat, lon)
    try:
        with store.tx("api") as c:
            row = c.execute("SELECT name, country FROM place_names WHERE cell = ?", (cell,)).fetchone()
    except Exception:
        log.exception("Place-name cache unavailable")
        row = None
    if row:
        return {"name": row["name"], "country": row["country"]} if row["name"] else None
    if not URL:
        return None
    address = _fetch(lat, lon)
    if address is None:
        return None  # temporary failure: not cached, try again next time
    name, country = _label(address), (address.get("country_code") or "").upper()
    try:
        with store.tx("api") as c:
            # An empty name is cached too (open sea, desert), so the same square is never asked twice
            c.execute("INSERT INTO place_names(cell, name, country, created_at) VALUES (?,?,?,?) "
                      "ON CONFLICT(cell) DO NOTHING", (cell, name, country, store.now()))
    except Exception:
        log.exception("Could not cache place name")
    return {"name": name, "country": country} if name else None
