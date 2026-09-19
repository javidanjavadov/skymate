"""Offline geocoding backed by the GeoNames cities15000 dataset (CC-BY 4.0)."""
import io
import logging
import math
import zipfile
from functools import lru_cache

import requests
from timezonefinder import TimezoneFinder

from . import db
from .config import STATIC_DIR

log = logging.getLogger("skymate.geo")

GEONAMES_URL = "https://download.geonames.org/export/dump/cities15000.zip"
LOCAL_ZIP = STATIC_DIR / "cities15000.zip"

_TRANSLIT = str.maketrans({
    'ç': 'c', 'ğ': 'g', 'ı': 'i', 'ö': 'o', 'ş': 's', 'ü': 'u', 'ə': 'e',
    'Ç': 'C', 'Ğ': 'G', 'İ': 'I', 'Ö': 'O', 'Ş': 'S', 'Ü': 'U', 'Ə': 'E',
})
_tf = TimezoneFinder()


def _norm(s: str) -> str:
    return " ".join(s.translate(_TRANSLIT).strip().casefold().split())


def ensure_loaded():
    conn = db.connect()
    if conn.execute("SELECT COUNT(*) FROM cities").fetchone()[0] > 0:
        return
    if not LOCAL_ZIP.exists():
        log.info("Downloading GeoNames city database (one-time)...")
        r = requests.get(GEONAMES_URL, timeout=120)
        r.raise_for_status()
        LOCAL_ZIP.write_bytes(r.content)
    rows = []
    with zipfile.ZipFile(LOCAL_ZIP) as z:
        with z.open("cities15000.txt") as f:
            for line in io.TextIOWrapper(f, encoding="utf-8"):
                p = line.rstrip("\n").split("\t")
                if len(p) < 18:
                    continue
                alts = {_norm(a) for a in p[3].split(",") if a}
                alts.add(_norm(p[1]))
                rows.append((int(p[0]), p[1], _norm(p[2]), "," + ",".join(sorted(alts)) + ",",
                             p[8], p[10], float(p[4]), float(p[5]), int(p[14] or 0), p[17]))
    with db.tx() as c:
        c.executemany("INSERT OR REPLACE INTO cities VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    log.info("Loaded %d cities.", len(rows))


def _row(r) -> dict:
    return {"name": r["name"], "country": r["country"], "lat": r["lat"], "lon": r["lon"],
            "population": r["population"], "timezone": r["timezone"]}


def search(query: str, limit: int = 5) -> list[dict]:
    q = _norm(query)
    country = None
    if "," in q:
        q, rest = [s.strip() for s in q.split(",", 1)]
        if len(rest) == 2:
            country = rest.upper()
    if not q:
        return []
    conn = db.connect()
    cf = " AND country = ?" if country else ""
    args = [country] if country else []
    rows = conn.execute(
        f"SELECT * FROM cities WHERE (ascii = ? OR alt LIKE ?){cf} ORDER BY population DESC LIMIT ?",
        [q, f"%,{q},%", *args, limit]).fetchall()
    if not rows:
        rows = conn.execute(
            f"SELECT * FROM cities WHERE ascii LIKE ?{cf} ORDER BY population DESC LIMIT ?",
            [f"{q}%", *args, limit]).fetchall()
    return [_row(r) for r in rows]


def suggest(prefix: str, limit: int = 6) -> list[dict]:
    """Places whose name (or an alternate name) starts with the typed text, biggest first."""
    q = _norm(prefix)
    if len(q) < 2:
        return []
    q = q.replace("%", "").replace("_", "")
    rows = db.connect().execute(
        "SELECT * FROM cities WHERE ascii LIKE ? OR alt LIKE ? "
        "ORDER BY (ascii = ?) DESC, (ascii LIKE ?) DESC, population DESC LIMIT ?",
        [f"{q}%", f"%,{q}%", q, f"{q}%", limit]).fetchall()
    return [_row(r) for r in rows]


def _haversine(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def reverse(lat: float, lon: float) -> dict | None:
    conn = db.connect()
    for box in (0.5, 1.5, 4.0):
        rows = conn.execute(
            "SELECT * FROM cities WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
            (lat - box, lat + box, lon - box, lon + box)).fetchall()
        if rows:
            best = min(rows, key=lambda r: _haversine(lat, lon, r["lat"], r["lon"]))
            out = _row(best)
            out["distance_km"] = round(_haversine(lat, lon, best["lat"], best["lon"]), 1)
            return out
    return None


@lru_cache(maxsize=4096)
def timezone_at(lat: float, lon: float) -> str:
    return _tf.timezone_at(lat=lat, lng=lon) or "UTC"


def largest_cities_in(lat_min, lat_max, lon_min, lon_max, limit=12) -> list[dict]:
    rows = db.connect().execute(
        "SELECT * FROM cities WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? "
        "ORDER BY population DESC LIMIT ?", (lat_min, lat_max, lon_min, lon_max, limit)).fetchall()
    return [_row(r) for r in rows]
