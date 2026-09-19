import sqlite3
import threading
from contextlib import contextmanager

from .config import DB_PATH

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash TEXT UNIQUE NOT NULL,
    key_prefix TEXT NOT NULL,
    name TEXT NOT NULL,
    plan TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS usage (
    key_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (key_id, day, endpoint)
);
CREATE TABLE IF NOT EXISTS runs (
    model TEXT NOT NULL,
    run TEXT NOT NULL,
    status TEXT NOT NULL,
    steps TEXT,
    source TEXT,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    error TEXT,
    PRIMARY KEY (model, run)
);
CREATE TABLE IF NOT EXISTS source_health (
    source TEXT PRIMARY KEY,
    last_ok TEXT,
    last_error TEXT,
    last_error_at TEXT
);
CREATE TABLE IF NOT EXISTS point_cache (
    cache_key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS cities (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    ascii TEXT NOT NULL,
    alt TEXT,
    country TEXT,
    admin1 TEXT,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    population INTEGER,
    timezone TEXT
);
CREATE INDEX IF NOT EXISTS idx_cities_ascii ON cities(ascii COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_cities_latlon ON cities(lat, lon);
"""


def connect() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn = conn
    return conn


@contextmanager
def tx():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init():
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()


def mark_source(source: str, ok: bool, error: str | None = None):
    with tx() as c:
        if ok:
            c.execute(
                "INSERT INTO source_health(source, last_ok) VALUES (?, datetime('now')) "
                "ON CONFLICT(source) DO UPDATE SET last_ok=datetime('now')", (source,))
        else:
            c.execute(
                "INSERT INTO source_health(source, last_error, last_error_at) VALUES (?, ?, datetime('now')) "
                "ON CONFLICT(source) DO UPDATE SET last_error=excluded.last_error, last_error_at=datetime('now')",
                (source, (error or "")[:500]))
