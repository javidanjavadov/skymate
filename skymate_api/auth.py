"""API keys, plans, rate limits and usage metering."""
import hashlib
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from . import db

PLANS = {
    "free": {"daily": 1_000, "per_minute": 60, "price_usd_month": 0},
    "starter": {"daily": 20_000, "per_minute": 300, "price_usd_month": 19},
    "pro": {"daily": 200_000, "per_minute": 1_200, "price_usd_month": 79},
    "business": {"daily": 2_000_000, "per_minute": 6_000, "price_usd_month": 299},
    "internal": {"daily": None, "per_minute": None, "price_usd_month": 0},
}


class AuthError(Exception):
    def __init__(self, status: int, message: str, headers: dict | None = None):
        super().__init__(message)
        self.status, self.message, self.headers = status, message, headers or {}


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create_key(name: str, plan: str = "free") -> str:
    if plan not in PLANS:
        raise ValueError(f"Unknown plan '{plan}'. Choose from: {', '.join(PLANS)}")
    key = "sk_" + secrets.token_urlsafe(30)
    with db.tx() as c:
        c.execute("INSERT INTO api_keys(key_hash, key_prefix, name, plan) VALUES (?,?,?,?)",
                  (_hash(key), key[:10], name, plan))
    return key


def list_keys() -> list[dict]:
    rows = db.connect().execute("SELECT id, key_prefix, name, plan, active, created_at FROM api_keys ORDER BY id")
    return [dict(r) for r in rows]


def set_active(key_id: int, active: bool):
    with db.tx() as c:
        c.execute("UPDATE api_keys SET active=? WHERE id=?", (1 if active else 0, key_id))


def set_plan(key_id: int, plan: str):
    if plan not in PLANS:
        raise ValueError(f"Unknown plan '{plan}'")
    with db.tx() as c:
        c.execute("UPDATE api_keys SET plan=? WHERE id=?", (plan, key_id))


def usage(days: int = 30) -> list[dict]:
    rows = db.connect().execute(
        "SELECT k.id, k.name, k.plan, u.day, SUM(u.count) AS requests FROM usage u JOIN api_keys k ON k.id=u.key_id "
        "WHERE u.day >= date('now', ?) GROUP BY k.id, u.day ORDER BY u.day DESC, requests DESC",
        (f"-{days} days",))
    return [dict(r) for r in rows]


_minute = defaultdict(deque)
_lock = threading.Lock()
_key_cache: dict[str, tuple[float, dict | None]] = {}


def _lookup(key: str) -> dict | None:
    h = _hash(key)
    hit = _key_cache.get(h)
    if hit and time.time() - hit[0] < 30:
        return hit[1]
    row = db.connect().execute("SELECT id, name, plan, active FROM api_keys WHERE key_hash=?", (h,)).fetchone()
    info = dict(row) if row else None
    _key_cache[h] = (time.time(), info)
    return info


def check(key: str | None, endpoint: str) -> tuple[dict, dict]:
    """Validates a key, enforces limits, records usage. Returns (key_info, response_headers)."""
    if not key:
        raise AuthError(401, "Missing API key. Send it in the X-API-Key header.")
    info = _lookup(key)
    if not info or not info["active"]:
        raise AuthError(401, "Invalid or revoked API key.")
    plan = PLANS.get(info["plan"], PLANS["free"])
    headers = {"X-Plan": info["plan"]}
    now = time.time()
    if plan["per_minute"]:
        with _lock:
            q = _minute[info["id"]]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= plan["per_minute"]:
                raise AuthError(429, "Rate limit exceeded (per minute).", {"Retry-After": "60"})
            q.append(now)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = db.connect()
    if plan["daily"]:
        used = conn.execute("SELECT COALESCE(SUM(count),0) FROM usage WHERE key_id=? AND day=?",
                            (info["id"], day)).fetchone()[0]
        if used >= plan["daily"]:
            raise AuthError(429, "Daily quota exceeded for your plan.", {"Retry-After": "3600"})
        headers["X-RateLimit-Remaining-Day"] = str(plan["daily"] - used - 1)
    with db.tx() as c:
        c.execute("INSERT INTO usage(key_id, day, endpoint, count) VALUES (?,?,?,1) "
                  "ON CONFLICT(key_id, day, endpoint) DO UPDATE SET count=count+1", (info["id"], day, endpoint))
    return info, headers
