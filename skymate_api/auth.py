"""API keys, plans, rate limits and usage metering."""
import hashlib
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from . import store

PLANS = {
    # API plans for developers and businesses
    "free": {"daily": 1_000, "per_minute": 60, "price_usd_month": 0,
             "max_forecast_days": 5, "max_history_days": 7},
    "starter": {"daily": 20_000, "per_minute": 300, "price_usd_month": 19,
                "max_forecast_days": 10, "max_history_days": 90},
    "pro": {"daily": 200_000, "per_minute": 1_200, "price_usd_month": 79,
            "max_forecast_days": 10, "max_history_days": 366},
    "business": {"daily": 2_000_000, "per_minute": 6_000, "price_usd_month": 299,
                 "max_forecast_days": 10, "max_history_days": 366},
    # Personal keys for the desktop app, issued by the Telegram bot
    "app_free": {"daily": 500, "per_minute": 30, "price_usd_month": 0,
                 "max_forecast_days": 5, "max_history_days": 7},
    "premium": {"daily": 5_000, "per_minute": 120, "price_usd_month": 2.99,
                "max_forecast_days": 10, "max_history_days": 366},
    "internal": {"daily": None, "per_minute": None, "price_usd_month": 0,
                 "max_forecast_days": 10, "max_history_days": 366},
}


def require(info: dict, limit: str, value: int):
    """Raise 403 if the key's plan does not allow `value` for the given limit."""
    allowed = PLANS.get(info["plan"], PLANS["free"]).get(limit)
    if allowed is not None and value > allowed:
        what = "forecast days" if limit == "max_forecast_days" else "days of history"
        raise AuthError(403, f"Your plan ({info['plan']}) allows up to {allowed} {what}. Upgrade for more.")


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
    with store.tx("api") as c:
        c.execute("INSERT INTO api_keys(key_hash, key_prefix, name, plan, created_at) VALUES (?,?,?,?,?)",
                  (_hash(key), key[:10], name, plan, store.now()))
    return key


def list_keys() -> list[dict]:
    with store.tx("api") as c:
        rows = c.execute("SELECT id, key_prefix, name, plan, active, created_at FROM api_keys ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def set_active(key_id: int, active: bool):
    with store.tx("api") as c:
        c.execute("UPDATE api_keys SET active=? WHERE id=?", (1 if active else 0, key_id))
    _key_cache.clear()


def set_plan(key_id: int, plan: str):
    if plan not in PLANS:
        raise ValueError(f"Unknown plan '{plan}'")
    with store.tx("api") as c:
        c.execute("UPDATE api_keys SET plan=? WHERE id=?", (plan, key_id))
    _key_cache.clear()


def usage(days: int = 30) -> list[dict]:
    with store.tx("api") as c:
        rows = c.execute(
            "SELECT k.id, k.name, k.plan, u.day, SUM(u.count) AS requests FROM usage u JOIN api_keys k ON k.id=u.key_id "
            "WHERE u.day >= ? GROUP BY k.id, k.name, k.plan, u.day ORDER BY u.day DESC, requests DESC",
            (store.today(-days),)).fetchall()
    return [dict(r) for r in rows]


_minute = defaultdict(deque)
_lock = threading.Lock()
_key_cache: dict[str, tuple[float, dict | None]] = {}


INTERNAL = {"id": 0, "name": "SkyMate internal (bot + app)", "plan": "internal", "active": 1}


def _lookup(key: str) -> dict | None:
    env_key = os.environ.get("SKYMATE_API_KEY", "")
    if env_key and secrets.compare_digest(key, env_key):
        return INTERNAL
    h = _hash(key)
    hit = _key_cache.get(h)
    if hit and time.time() - hit[0] < 30:
        return hit[1]
    with store.tx("api") as c:
        row = c.execute("SELECT id, name, plan, active FROM api_keys WHERE key_hash=?", (h,)).fetchone()
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
    with store.tx("api") as c:
        if plan["daily"]:
            used = c.execute("SELECT COALESCE(SUM(count),0) FROM usage WHERE key_id=? AND day=?",
                             (info["id"], day)).fetchone()[0]
            if used >= plan["daily"]:
                raise AuthError(429, "Daily quota exceeded for your plan.", {"Retry-After": "3600"})
            headers["X-RateLimit-Remaining-Day"] = str(plan["daily"] - used - 1)
        c.execute("INSERT INTO usage(key_id, day, endpoint, count) VALUES (?,?,?,1) "
                  "ON CONFLICT(key_id, day, endpoint) DO UPDATE SET count=usage.count+1", (info["id"], day, endpoint))
    return info, headers
