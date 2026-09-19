"""Persistent account data: bot users, payments, Premium, API keys and usage.

Locally this is SQLite (bot_data.db and data/skymate.db). When DATABASE_URL is set (cloud hosting
whose disk is wiped on restart) everything goes to Postgres instead. SQL is written in the subset both
understand: ? placeholders, ON CONFLICT upserts, and timestamps passed in from Python.
"""
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from .config import DATA_DIR, ROOT

DATABASE_URL = os.environ.get("DATABASE_URL", "")
IS_PG = DATABASE_URL.startswith(("postgres://", "postgresql://"))
SQLITE_FILES = {"bot": ROOT / "bot_data.db", "api": DATA_DIR / "skymate.db"}

_local = threading.local()

_T = {
    "BIGINT": "BIGINT",
    "AUTOID": "BIGSERIAL PRIMARY KEY" if IS_PG else "INTEGER PRIMARY KEY AUTOINCREMENT",
    "NOW": ("(to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS'))" if IS_PG else "(datetime('now'))"),
}

SCHEMAS = {
    "api": [
        """CREATE TABLE IF NOT EXISTS api_keys (id {AUTOID}, key_hash TEXT UNIQUE NOT NULL, key_prefix TEXT NOT NULL,
           name TEXT NOT NULL, plan TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT {NOW})""",
        """CREATE TABLE IF NOT EXISTS usage (key_id {BIGINT} NOT NULL, day TEXT NOT NULL, endpoint TEXT NOT NULL,
           count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (key_id, day, endpoint))""",
    ],
    "bot": [
        "CREATE TABLE IF NOT EXISTS user_settings (user_id {BIGINT} PRIMARY KEY, units TEXT DEFAULT 'metric')",
        "CREATE TABLE IF NOT EXISTS user_favorites (user_id {BIGINT}, city TEXT, PRIMARY KEY (user_id, city))",
        "CREATE TABLE IF NOT EXISTS user_subscriptions (user_id {BIGINT} PRIMARY KEY, chat_id {BIGINT}, city TEXT, units TEXT)",
        """CREATE TABLE IF NOT EXISTS premium (user_id {BIGINT} PRIMARY KEY, until {BIGINT}, charge_id TEXT,
           recurring INTEGER, updated_at TEXT DEFAULT {NOW})""",
        """CREATE TABLE IF NOT EXISTS payments (charge_id TEXT PRIMARY KEY, user_id {BIGINT}, stars INTEGER, until {BIGINT},
           refunded INTEGER DEFAULT 0, created_at TEXT DEFAULT {NOW})""",
        "CREATE TABLE IF NOT EXISTS app_keys (user_id {BIGINT} PRIMARY KEY, plan TEXT, created_at TEXT DEFAULT {NOW})",
        """CREATE TABLE IF NOT EXISTS alert_sent (user_id {BIGINT}, alert_key TEXT, sent_at TEXT DEFAULT {NOW},
           PRIMARY KEY (user_id, alert_key))""",
        """CREATE TABLE IF NOT EXISTS users (user_id {BIGINT} PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT,
           language TEXT, first_seen TEXT, last_seen TEXT, actions INTEGER DEFAULT 0)""",
    ],
}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def today(offset_days: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=offset_days)).strftime("%Y-%m-%d")


class Row(tuple):
    """Postgres rows that behave like sqlite3.Row: row[0], row['col'] and dict(row)."""

    def __new__(cls, values, names):
        r = super().__new__(cls, values)
        r._names = names
        return r

    def __getitem__(self, k):
        if isinstance(k, str):
            return tuple.__getitem__(self, self._names.index(k))
        return tuple.__getitem__(self, k)

    def keys(self):
        return self._names


def _pg_rows(cursor):
    names = [c.name for c in cursor.description] if cursor.description else []
    return lambda values: Row(values, names)


class Conn:
    def __init__(self, raw):
        self.raw = raw

    @staticmethod
    def _sql(sql: str) -> str:
        return sql.replace("%", "%%").replace("?", "%s") if IS_PG else sql

    def execute(self, sql: str, args=()):
        cur = self.raw.cursor()
        cur.execute(self._sql(sql), tuple(args))
        return cur

    def executemany(self, sql: str, rows):
        cur = self.raw.cursor()
        cur.executemany(self._sql(sql), [tuple(r) for r in rows])
        return cur


def _raw(name: str):
    if IS_PG:
        import psycopg
        c = getattr(_local, "pg", None)
        if c is None or c.closed or c.broken:
            c = psycopg.connect(DATABASE_URL, row_factory=_pg_rows, connect_timeout=15)
            _local.pg = c
        return c
    key = f"sqlite_{name}"
    c = getattr(_local, key, None)
    if c is None:
        c = sqlite3.connect(SQLITE_FILES[name], timeout=30, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        setattr(_local, key, c)
    return c


@contextmanager
def tx(name: str = "bot"):
    """A transaction on the named store ('bot' or 'api'); commits on success."""
    try:
        raw = _raw(name)
    except Exception:
        if IS_PG:
            _local.pg = None
        raw = _raw(name)
    try:
        yield Conn(raw)
        raw.commit()
    except Exception:
        try:
            raw.rollback()
        except Exception:
            if IS_PG:
                _local.pg = None
        raise


def init(name: str):
    with tx(name) as c:
        for stmt in SCHEMAS[name]:
            c.execute(stmt.format(**_T))
