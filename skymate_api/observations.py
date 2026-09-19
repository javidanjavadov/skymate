"""Measured weather observations: collected from public station networks and archived permanently.

Live sources (tried in order, all public / free for commercial use):
  METAR  airport stations  - NOAA Aviation Weather Center bulk feed, then NOAA NWS cycle files
  SYNOP  official stations - Ogimet (Spain) WMO SYNOP reports
History:
  NOAA ISD-Lite hourly station records (decades back), downloaded once per station-year.
Every reading is stored in data/observations.db and never deleted.
"""
import gzip
import io
import json
import logging
import math
import os
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests

from . import db as maindb
from . import physics
from .config import DATA_DIR

log = logging.getLogger("skymate.obs")

OBS_DB = DATA_DIR / "observations.db"
SYNOP_STATES = [s.strip() for s in os.environ.get("SKYMATE_SYNOP_STATES", "Azer").split(",") if s.strip()]
ISD_COUNTRIES = [s.strip() for s in os.environ.get("SKYMATE_ISD_COUNTRIES", "AJ").split(",") if s.strip()]

_local = threading.local()
_session = requests.Session()
_session.headers["User-Agent"] = "SkyMate-Observations/1.0"

SCHEMA = """
CREATE TABLE IF NOT EXISTS stations (
    id TEXT PRIMARY KEY,          -- ICAO code (airports) or WMO number (official stations)
    name TEXT, country TEXT, lat REAL, lon REAL, elevation REAL,
    icao TEXT, wmo TEXT, kind TEXT, updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_st_latlon ON stations(lat, lon);
CREATE TABLE IF NOT EXISTS obs (
    station_id TEXT NOT NULL,
    time INTEGER NOT NULL,        -- unix seconds, UTC
    temperature REAL, dew_point REAL, humidity REAL, pressure REAL,
    wind_direction REAL, wind_speed REAL, wind_gust REAL, visibility REAL,
    cloud_cover REAL, precipitation REAL, precipitation_hours REAL,
    weather TEXT, source TEXT, raw TEXT,
    PRIMARY KEY (station_id, time)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS backfill_done (key TEXT PRIMARY KEY, rows INTEGER, done_at TEXT);
"""

COLUMNS = ["station_id", "time", "temperature", "dew_point", "humidity", "pressure", "wind_direction",
           "wind_speed", "wind_gust", "visibility", "cloud_cover", "precipitation", "precipitation_hours",
           "weather", "source", "raw"]


def conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(OBS_DB, timeout=60, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.executescript(SCHEMA)
        _local.conn = c
    return c


def _store(rows: list[dict]) -> int:
    if not rows:
        return 0
    c = conn()
    before = c.total_changes
    c.executemany(f"INSERT OR IGNORE INTO obs({','.join(COLUMNS)}) VALUES ({','.join('?' * len(COLUMNS))})",
                  [[r.get(k) for k in COLUMNS] for r in rows])
    c.commit()
    return c.total_changes - before


def _upsert_stations(rows: list[dict]):
    if not rows:
        return
    c = conn()
    c.executemany(
        "INSERT INTO stations(id, name, country, lat, lon, elevation, icao, wmo, kind, updated_at) "
        "VALUES (:id, :name, :country, :lat, :lon, :elevation, :icao, :wmo, :kind, datetime('now')) "
        "ON CONFLICT(id) DO UPDATE SET name=COALESCE(excluded.name, name), country=COALESCE(excluded.country, country), "
        "lat=excluded.lat, lon=excluded.lon, elevation=COALESCE(excluded.elevation, elevation), "
        "icao=COALESCE(excluded.icao, icao), wmo=COALESCE(excluded.wmo, wmo), kind=excluded.kind, "
        "updated_at=datetime('now')", rows)
    c.commit()


def _get(url, timeout=60, **kw) -> requests.Response:
    r = _session.get(url, timeout=timeout, **kw)
    r.raise_for_status()
    return r


def _rh(t, td):
    return None if t is None or td is None else round(physics.rh_from_dewpoint(t, td), 1)


# ─── METAR ───────────────────────────────────────────────────────────────────

_WX_WORDS = {"TS": "thunderstorm", "SH": "showers", "FZ": "freezing", "DZ": "drizzle", "RA": "rain", "SN": "snow",
             "SG": "snow grains", "PL": "ice pellets", "GR": "hail", "GS": "small hail", "BR": "mist", "FG": "fog",
             "FU": "smoke", "HZ": "haze", "DU": "dust", "SA": "sand", "SQ": "squalls", "FC": "funnel cloud",
             "SS": "sandstorm", "DS": "duststorm", "VA": "volcanic ash", "BL": "blowing", "DR": "drifting",
             "MI": "shallow", "BC": "patches of", "PR": "partial", "UP": "precipitation"}
_WX_RE = re.compile(r"^(\+|-|VC)?((?:MI|PR|BC|DR|BL|SH|TS|FZ)?(?:DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS)*)$")
_CLOUD = {"FEW": 19, "SCT": 44, "BKN": 75, "OVC": 100, "VV": 100}


def describe_metar_wx(codes: list[str]) -> str | None:
    out = []
    for code in codes:
        m = _WX_RE.match(code)
        if not m or not m.group(2):
            continue
        body = m.group(2)
        words = [_WX_WORDS.get(body[i:i + 2], body[i:i + 2]) for i in range(0, len(body), 2)]
        prefix = {"-": "light ", "+": "heavy ", "VC": "nearby "}.get(m.group(1) or "", "")
        out.append(prefix + " ".join(words))
    return ", ".join(out) or None


def parse_metar(raw: str, ref: datetime | None = None, source: str = "metar") -> dict | None:
    tokens = raw.replace("=", "").split()
    while tokens and tokens[0] in ("METAR", "SPECI"):
        tokens.pop(0)
    if len(tokens) < 3 or not re.fullmatch(r"\d{6}Z", tokens[1]):
        return None
    station = tokens[0]
    ref = ref or datetime.now(timezone.utc)
    day, hour, minute = int(tokens[1][:2]), int(tokens[1][2:4]), int(tokens[1][4:6])
    try:
        t = ref.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
    except ValueError:
        return None
    if t > ref + timedelta(days=1):
        t = (t.replace(day=1) - timedelta(days=1)).replace(day=day)
    r = {"station_id": station, "time": int(t.timestamp()), "source": source, "raw": raw.strip()}
    clouds, wx = [], []
    for tok in tokens[2:]:
        if tok in ("RMK", "TEMPO", "BECMG", "NOSIG"):
            break
        if m := re.fullmatch(r"(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?(KT|MPS|KMH)", tok):
            f = {"KT": 0.514444, "MPS": 1.0, "KMH": 1 / 3.6}[m.group(4)]
            r["wind_direction"] = None if m.group(1) == "VRB" else float(m.group(1))
            r["wind_speed"] = round(int(m.group(2)) * f, 1)
            if m.group(3):
                r["wind_gust"] = round(int(m.group(3)) * f, 1)
        elif re.fullmatch(r"\d{4}", tok) and "visibility" not in r:
            r["visibility"] = 10000.0 if tok == "9999" else float(tok)
        elif tok == "CAVOK":
            r["visibility"], r["cloud_cover"] = 10000.0, 0.0
        elif m := re.fullmatch(r"P?(\d+)(?:/(\d+))?SM", tok):
            miles = int(m.group(1)) / int(m.group(2)) if m.group(2) else int(m.group(1))
            r["visibility"] = round(miles * 1609.34)
        elif m := re.fullmatch(r"(M?\d{2})/(M?\d{2})?", tok):
            conv = lambda s: -int(s[1:]) if s.startswith("M") else int(s)
            r["temperature"] = float(conv(m.group(1)))
            if m.group(2):
                r["dew_point"] = float(conv(m.group(2)))
        elif m := re.fullmatch(r"Q(\d{4})", tok):
            r["pressure"] = float(m.group(1))
        elif m := re.fullmatch(r"A(\d{4})", tok):
            r["pressure"] = round(int(m.group(1)) / 100 * 33.8639, 1)
        elif m := re.match(r"(FEW|SCT|BKN|OVC|VV)(\d{3}|///)", tok):
            clouds.append(_CLOUD[m.group(1)])
        elif tok in ("SKC", "CLR", "NSC", "NCD"):
            clouds.append(0)
        elif _WX_RE.match(tok) and not tok.isdigit() and tok not in ("AUTO", "COR"):
            wx.append(tok)
    if m := re.search(r"\bT([01])(\d{3})([01])(\d{3})\b", raw):
        r["temperature"] = (-1 if m.group(1) == "1" else 1) * int(m.group(2)) / 10
        r["dew_point"] = (-1 if m.group(3) == "1" else 1) * int(m.group(4)) / 10
    if clouds and "cloud_cover" not in r:
        r["cloud_cover"] = float(max(clouds))
    r["weather"] = describe_metar_wx(wx)
    r["humidity"] = _rh(r.get("temperature"), r.get("dew_point"))
    return r if r.get("temperature") is not None or r.get("wind_speed") is not None else None


def collect_metar_awc() -> int:
    raw = gzip.decompress(_get("https://aviationweather.gov/data/cache/metars.cache.csv.gz").content).decode()
    rows = []
    lines = raw.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("raw_text,"))
    import csv
    for rec in csv.DictReader(lines[start:]):
        t = datetime.strptime(rec["observation_time"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        parsed = parse_metar(rec["raw_text"], ref=t + timedelta(hours=1), source="noaa-awc")
        if parsed:
            parsed["time"] = int(t.timestamp())
            rows.append(parsed)
    return _store(rows)


def collect_metar_nws() -> int:
    now = datetime.now(timezone.utc)
    rows = []
    for h in (now.hour, (now - timedelta(hours=1)).hour):
        text = _get(f"https://tgftp.nws.noaa.gov/data/observations/metar/cycles/{h:02d}Z.TXT").text
        for line in text.splitlines():
            if re.match(r"^[A-Z0-9]{4} \d{6}Z", line):
                p = parse_metar(line, ref=now, source="noaa-nws")
                if p:
                    rows.append(p)
    return _store(rows)


def refresh_airport_stations():
    data = json.loads(gzip.decompress(_get("https://aviationweather.gov/data/cache/stations.cache.json.gz").content))
    rows = [{"id": s["icaoId"], "name": s.get("site"), "country": s.get("country"), "lat": s["lat"], "lon": s["lon"],
             "elevation": s.get("elev"), "icao": s["icaoId"], "wmo": s.get("wmoId"), "kind": "airport"}
            for s in data if s.get("icaoId") and s.get("lat") is not None and "METAR" in (s.get("siteType") or [])]
    _upsert_stations(rows)
    # Official WMO stations that share a site with an airport inherit its ISO country code.
    conn().executemany("UPDATE stations SET country=? WHERE id=? AND kind='official'",
                       [(r["country"], r["wmo"]) for r in rows if r["wmo"]])
    conn().commit()
    return len(rows)


# ─── SYNOP ───────────────────────────────────────────────────────────────────

def _synop_ww(ww: int) -> str | None:
    if ww < 4:
        return None
    for lo, hi, text in [(4, 5, "haze/smoke"), (6, 9, "dust"), (10, 12, "mist"), (13, 13, "lightning"),
                         (17, 17, "thunderstorm"), (18, 18, "squalls"), (20, 29, None), (30, 35, "duststorm"),
                         (36, 39, "blowing snow"), (40, 49, "fog"), (50, 59, "drizzle"), (60, 69, "rain"),
                         (70, 79, "snow"), (80, 82, "rain showers"), (83, 86, "snow showers"), (87, 90, "hail"),
                         (91, 99, "thunderstorm")]:
        if lo <= ww <= hi:
            return text
    return None


def parse_synop(line: str) -> dict | None:
    parts = line.split(",", 6)
    if len(parts) < 7 or "NIL" in parts[6]:
        return None
    wmo = parts[0]
    t = datetime(int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4]), int(parts[5]), tzinfo=timezone.utc)
    g = parts[6].replace("=", "").split()
    if len(g) < 5 or g[0] != "AAXX":
        return None
    iw = g[1][-1]
    speed_factor = 0.514444 if iw in ("3", "4") else 1.0
    r = {"station_id": wmo, "time": int(t.timestamp()), "source": "ogimet-synop", "raw": parts[6].strip()}
    i = 3
    ix_vv = g[i] if i < len(g) else ""
    if len(ix_vv) == 5 and ix_vv[3:].isdigit():
        vv = int(ix_vv[3:])
        if vv <= 50:
            r["visibility"] = vv * 100.0
        elif 56 <= vv <= 80:
            r["visibility"] = (vv - 50) * 1000.0
        elif 81 <= vv <= 88:
            r["visibility"] = (30 + (vv - 80) * 5) * 1000.0
        elif vv == 89:
            r["visibility"] = 75000.0
    nddff = g[i + 1] if i + 1 < len(g) else ""
    if len(nddff) == 5:
        if nddff[0].isdigit() and nddff[0] != "9":
            r["cloud_cover"] = round(int(nddff[0]) / 8 * 100)
        if nddff[1:3].isdigit():
            dd = int(nddff[1:3])
            r["wind_direction"] = None if dd in (0, 99) else dd * 10.0
        if nddff[3:].isdigit():
            r["wind_speed"] = round(int(nddff[3:]) * speed_factor, 1)
    for grp in g[i + 2:]:
        if grp in ("333", "555") or len(grp) != 5:
            if grp in ("333", "555"):
                break
            continue
        k, v = grp[0], grp[1:]
        if "/" in v:
            continue
        if k == "1" and v[0] in "01":
            r["temperature"] = (-1 if v[0] == "1" else 1) * int(v[1:]) / 10
        elif k == "2" and v[0] in "01":
            r["dew_point"] = (-1 if v[0] == "1" else 1) * int(v[1:]) / 10
        elif k == "2" and v[0] == "9":
            r["humidity"] = float(int(v[1:]))
        elif k == "4" and v[0] in "09":
            p = int(v) / 10
            r["pressure"] = p + 1000 if p < 100 else p
        elif k == "6":
            rrr, tr = int(v[:3]), v[3]
            r["precipitation"] = 0.0 if rrr == 990 else (rrr - 990) / 10 if rrr > 990 else float(rrr)
            r["precipitation_hours"] = {"1": 6, "2": 12, "3": 18, "4": 24, "5": 1, "6": 2, "7": 3, "8": 9, "9": 15}.get(tr)
        elif k == "7":
            r["weather"] = _synop_ww(int(v[:2]))
    if r.get("humidity") is None:
        r["humidity"] = _rh(r.get("temperature"), r.get("dew_point"))
    return r if r.get("temperature") is not None else None


def collect_synop() -> int:
    end = datetime.now(timezone.utc)
    begin = end - timedelta(hours=6)
    rows = []
    for state in SYNOP_STATES:
        text = _get("https://www.ogimet.com/cgi-bin/getsynop",
                    params={"begin": begin.strftime("%Y%m%d%H00"), "end": end.strftime("%Y%m%d%H00"), "state": state}).text
        rows += [p for p in (parse_synop(l) for l in text.splitlines()) if p]
        time.sleep(2)
    return _store(rows)


# ─── Historical archive (NOAA ISD-Lite) ──────────────────────────────────────

def _isd_station_id(usaf: str) -> str:
    return usaf[:5] if usaf.endswith("0") else f"isd:{usaf}"


def refresh_official_stations() -> list[dict]:
    text = _get("https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv", timeout=120).text
    import csv
    stations = [r for r in csv.DictReader(io.StringIO(text)) if r["CTRY"] in ISD_COUNTRIES and r["LAT"] and r["LON"]]
    _upsert_stations([{
        "id": _isd_station_id(r["USAF"]), "name": r["STATION NAME"].title(), "country": None,
        "lat": float(r["LAT"]), "lon": float(r["LON"]), "elevation": float(r["ELEV(M)"]) if r["ELEV(M)"] else None,
        "icao": r["ICAO"] or None, "wmo": r["USAF"][:5] if r["USAF"].endswith("0") else None, "kind": "official",
    } for r in stations])
    return stations


def _parse_isd_lite(text: str, station_id: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        p = line.split()
        if len(p) < 12:
            continue
        val = lambda s, scale=10: None if s == "-9999" else int(s) / scale
        t = datetime(int(p[0]), int(p[1]), int(p[2]), int(p[3]), tzinfo=timezone.utc)
        temp, dew = val(p[4]), val(p[5])
        precip1, precip6 = val(p[10]), val(p[11])
        sky = None if p[9] == "-9999" else int(p[9])
        rows.append({
            "station_id": station_id, "time": int(t.timestamp()), "temperature": temp, "dew_point": dew,
            "humidity": _rh(temp, dew), "pressure": val(p[6]),
            "wind_direction": None if p[7] in ("-9999", "0") else float(p[7]), "wind_speed": val(p[8]),
            "cloud_cover": round(min(sky, 8) / 8 * 100) if sky is not None and sky <= 10 else None,
            "precipitation": precip1 if precip1 is not None else precip6,
            "precipitation_hours": 1 if precip1 is not None else (6 if precip6 is not None else None),
            "source": "noaa-isd", "raw": None})
    return rows


def backfill_isd():
    """Download every available year of hourly history for the configured countries (resumable)."""
    stations = refresh_official_stations()
    this_year = datetime.now(timezone.utc).year
    done = {r[0] for r in conn().execute("SELECT key FROM backfill_done")}
    todo = []
    for s in stations:
        start = int(s["BEGIN"][:4]) if s["BEGIN"] else 1930
        end = int(s["END"][:4]) if s["END"] else this_year
        for y in range(max(start, 1901), min(max(end, this_year), this_year) + 1):
            key = f"{s['USAF']}-{s['WBAN']}-{y}"
            if key not in done or y >= this_year - 1:
                todo.append((s, y, key))
    if not todo:
        return
    log.info("History backfill: %d station-years to fetch from NOAA ISD", len(todo))

    def work(item):
        s, y, key = item
        url = f"https://www.ncei.noaa.gov/pub/data/noaa/isd-lite/{y}/{s['USAF']}-{s['WBAN']}-{y}.gz"
        try:
            r = _session.get(url, timeout=60)
            if r.status_code == 404:
                rows = []
            else:
                r.raise_for_status()
                rows = _parse_isd_lite(gzip.decompress(r.content).decode(), _isd_station_id(s["USAF"]))
        except Exception as e:
            log.warning("ISD %s: %s", key, e)
            return 0
        n = _store(rows)
        if y < this_year - 1:
            c = conn()
            c.execute("INSERT OR REPLACE INTO backfill_done VALUES (?,?,datetime('now'))", (key, len(rows)))
            c.commit()
        return n

    total = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for k, n in enumerate(pool.map(work, todo), 1):
            total += n
            if k % 200 == 0:
                log.info("History backfill: %d/%d files, %d readings added", k, len(todo), total)
    log.info("History backfill complete: %d readings added", total)


def fill_recent_synop(months: int = 18):
    """NOAA's archive lags by months; fill that gap with the national services' own SYNOP reports."""
    now = datetime.now(timezone.utc)
    done = {r[0] for r in conn().execute("SELECT key FROM backfill_done WHERE key LIKE 'ogimet-%'")}
    first = (now.replace(day=1) - timedelta(days=31 * months)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month = first
    while month <= now:
        nxt = (month + timedelta(days=32)).replace(day=1)
        for state in SYNOP_STATES:
            key = f"ogimet-{state}-{month:%Y%m}"
            if key in done:
                continue
            try:
                text = _get("https://www.ogimet.com/cgi-bin/getsynop", timeout=120,
                            params={"begin": month.strftime("%Y%m%d0000"),
                                    "end": (min(nxt, now) - timedelta(minutes=1)).strftime("%Y%m%d%H%M"),
                                    "state": state}).text
                n = _store([p for p in (parse_synop(l) for l in text.splitlines()) if p])
                log.info("SYNOP gap fill %s %s: %d readings", state, f"{month:%Y-%m}", n)
                if nxt <= now:
                    c = conn()
                    c.execute("INSERT OR REPLACE INTO backfill_done VALUES (?,?,datetime('now'))", (key, n))
                    c.commit()
            except Exception as e:
                log.warning("SYNOP gap fill %s failed: %s", key, e)
            time.sleep(25)  # Ogimet allows one heavy query per 20 s per IP
        month = nxt


# ─── Collection cycle (with source failover) ─────────────────────────────────

def collect_all():
    added = 0
    for name, fn in (("noaa-awc", collect_metar_awc), ("noaa-nws", collect_metar_nws)):
        try:
            n = fn()
            maindb.mark_source(f"obs:{name}", True)
            added += n
            log.info("METAR from %s: %d new readings", name, n)
            break
        except Exception as e:
            maindb.mark_source(f"obs:{name}", False, str(e))
            log.warning("METAR source %s failed: %s", name, e)
    try:
        n = collect_synop()
        maindb.mark_source("obs:ogimet", True)
        added += n
        log.info("SYNOP from ogimet: %d new readings", n)
    except Exception as e:
        maindb.mark_source("obs:ogimet", False, str(e))
        log.warning("SYNOP source failed: %s", e)
    return added


# ─── Queries ─────────────────────────────────────────────────────────────────

def _dist(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(a))


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _ts(t: int) -> datetime:
    return _EPOCH + timedelta(seconds=t)


def _obs_dict(row) -> dict:
    d = dict(row)
    d["time"] = _ts(d["time"]).isoformat()
    d.pop("station_id", None)
    return d


def nearby(lat: float, lon: float, radius_km: float = 50, limit: int = 5, max_age_hours: float = 3) -> list[dict]:
    box = radius_km / 111 + 0.1
    c = conn()
    stations = c.execute("SELECT * FROM stations WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
                         (lat - box, lat + box, lon - box / max(0.2, math.cos(math.radians(lat))),
                          lon + box / max(0.2, math.cos(math.radians(lat))))).fetchall()
    cutoff = int(time.time() - max_age_hours * 3600)
    out = []
    for s in stations:
        d = _dist(lat, lon, s["lat"], s["lon"])
        if d > radius_km:
            continue
        row = c.execute("SELECT * FROM obs WHERE station_id=? AND time>=? ORDER BY time DESC LIMIT 1",
                        (s["id"], cutoff)).fetchone()
        if row:
            o = _obs_dict(row)
            o["age_minutes"] = round((time.time() - row["time"]) / 60)
            out.append({"station": _station_dict(s, d), "observation": o})
    # A reading an hour older counts like being ~10 km farther away.
    out.sort(key=lambda x: x["station"]["distance_km"] + x["observation"]["age_minutes"] / 6)
    return out[:limit]


def _station_dict(s, distance=None) -> dict:
    d = {k: s[k] for k in ("id", "name", "country", "lat", "lon", "elevation", "icao", "wmo", "kind")}
    if distance is not None:
        d["distance_km"] = round(distance, 1)
    return d


def stations_near(lat: float, lon: float, radius_km: float = 100, limit: int = 20) -> list[dict]:
    box = radius_km / 111 + 0.1
    rows = conn().execute("SELECT * FROM stations WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
                          (lat - box, lat + box, lon - box * 2, lon + box * 2)).fetchall()
    out = [(_dist(lat, lon, s["lat"], s["lon"]), s) for s in rows]
    return [_station_dict(s, d) for d, s in sorted(out, key=lambda x: x[0]) if d <= radius_km][:limit]


def station(station_id: str) -> dict | None:
    s = conn().execute("SELECT * FROM stations WHERE id=?", (station_id.upper(),)).fetchone()
    return _station_dict(s) if s else None


def history(station_id: str, start: datetime, end: datetime, limit: int = 20000) -> list[dict]:
    rows = conn().execute("SELECT * FROM obs WHERE station_id=? AND time BETWEEN ? AND ? ORDER BY time LIMIT ?",
                          (station_id.upper(), int(start.timestamp()), int(end.timestamp()), limit)).fetchall()
    return [_obs_dict(r) for r in rows]


def coverage(station_id: str) -> dict:
    r = conn().execute("SELECT MIN(time), MAX(time), COUNT(*) FROM obs WHERE station_id=?", (station_id.upper(),)).fetchone()
    iso = lambda t: _ts(t).isoformat() if t is not None else None
    return {"from": iso(r[0]), "to": iso(r[1]), "readings": r[2]}


def stats() -> dict:
    c = conn()
    total = c.execute("SELECT COUNT(*) FROM obs").fetchone()[0]
    last = c.execute("SELECT MAX(time) FROM obs WHERE source != 'noaa-isd'").fetchone()[0]
    first = c.execute("SELECT MIN(time) FROM obs").fetchone()[0]
    iso = lambda t: _ts(t).isoformat() if t is not None else None
    return {"readings": total, "stations": c.execute("SELECT COUNT(*) FROM stations").fetchone()[0],
            "oldest_reading": iso(first), "latest_live_reading": iso(last),
            "database_mb": round(OBS_DB.stat().st_size / 1e6, 1) if OBS_DB.exists() else 0}
