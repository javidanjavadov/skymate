"""Last known dashboards, so the website keeps answering while forecast files are reloading.

Render's free plan gives no permanent disk, so every restart wipes the decoded forecast grids and the service needs
a few minutes to rebuild them. Each successful dashboard is stored in the database (which does survive restarts) and
served in the meantime, labelled with the time it was produced.
"""
import json
import logging
from datetime import datetime, timezone

from . import store

log = logging.getLogger("skymate.lastknown")

SCHEMA = ("CREATE TABLE IF NOT EXISTS last_dashboard (place TEXT PRIMARY KEY, body TEXT NOT NULL, "
          "made_at TEXT NOT NULL)")
MAX_AGE_HOURS = 24
KEEP_ROWS = 2000


def init():
    with store.tx("api") as c:
        c.execute(SCHEMA)


def key(q: str | None, lat: float | None, lon: float | None) -> str:
    """One entry per place: a city name, or coordinates rounded to ~1 km."""
    return q.strip().lower() if q else f"{lat:.2f},{lon:.2f}"


def save(place: str, dashboard: dict):
    try:
        with store.tx("api") as c:
            c.execute("INSERT INTO last_dashboard(place, body, made_at) VALUES (?,?,?) "
                      "ON CONFLICT(place) DO UPDATE SET body=excluded.body, made_at=excluded.made_at",
                      (place, json.dumps(dashboard), store.now()))
    except Exception:
        log.exception("Could not store the last known dashboard")


def load(place: str) -> dict | None:
    """The stored dashboard for this place, marked as stale, or None when there is nothing recent."""
    try:
        with store.tx("api") as c:
            row = c.execute("SELECT body, made_at FROM last_dashboard WHERE place = ?", (place,)).fetchone()
    except Exception:
        log.exception("Could not read the last known dashboard")
        return None
    if not row:
        return None
    made_at = str(row["made_at"]).replace(" ", "T")
    try:
        made = datetime.fromisoformat(made_at).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    age_hours = (datetime.now(timezone.utc) - made).total_seconds() / 3600
    if age_hours > MAX_AGE_HOURS:
        return None
    body = json.loads(row["body"])
    body["meta"] = {**body.get("meta", {}), "stale": True, "made_at": made.isoformat().replace("+00:00", "Z"),
                    "stale_age_minutes": round(age_hours * 60)}
    return body


def cleanup():
    """Keeps the table small; safe to call occasionally."""
    try:
        with store.tx("api") as c:
            c.execute("DELETE FROM last_dashboard WHERE made_at < ?", (store.ago(2),))
    except Exception:
        log.exception("Could not clean up stored dashboards")
