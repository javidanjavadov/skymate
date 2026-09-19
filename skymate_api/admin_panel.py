"""Owner admin panel: users, payments, API customers, usage and data health. Served at /admin."""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from fastapi import APIRouter, Depends, Header
from fastapi.responses import HTMLResponse

from . import auth, db, forecast, store
from .config import ADMIN_TOKEN
PAGE = Path(__file__).parent / "static" / "admin.html"


def require_admin(x_admin_token: str | None = Header(None)):
    import secrets
    if not ADMIN_TOKEN or not x_admin_token or not secrets.compare_digest(x_admin_token, ADMIN_TOKEN):
        raise auth.AuthError(401, "Admin token required.")


router = APIRouter()
api = APIRouter(prefix="/admin/api", dependencies=[Depends(require_admin)], tags=["admin"])


@router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
def page():
    return PAGE.read_text(encoding="utf-8")


def _bot():
    return store.tx("bot")


def _api():
    return store.tx("api")


def _rows(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def _one(conn, sql, args=(), default=0):
    r = conn.execute(sql, args).fetchone()
    return r[0] if r and r[0] is not None else default


def _now() -> int:
    return int(datetime.now(timezone.utc).timestamp())


@api.get("/overview")
def overview():
    now = _now()
    with _bot() as b:
        bot = {
            "users": _one(b, "SELECT COUNT(*) FROM users"),
            "active_24h": _one(b, "SELECT COUNT(*) FROM users WHERE last_seen >= ?", (store.ago(1),)),
            "active_7d": _one(b, "SELECT COUNT(*) FROM users WHERE last_seen >= ?", (store.ago(7),)),
            "new_7d": _one(b, "SELECT COUNT(*) FROM users WHERE first_seen >= ?", (store.ago(7),)),
            "premium_active": _one(b, "SELECT COUNT(*) FROM premium WHERE until > ?", (now,)),
            "daily_subscriptions": _one(b, "SELECT COUNT(*) FROM user_subscriptions"),
            "app_keys": _one(b, "SELECT COUNT(*) FROM app_keys"),
            "stars_30d": _one(b, "SELECT SUM(stars) FROM payments WHERE refunded=0 AND created_at >= ?", (store.ago(30),)),
            "payments_30d": _one(b, "SELECT COUNT(*) FROM payments WHERE refunded=0 AND stars > 0 AND created_at >= ?", (store.ago(30),)),
            "stars_total": _one(b, "SELECT SUM(stars) FROM payments WHERE refunded=0"),
        }
    keys = [k for k in auth.list_keys() if not k["name"].startswith("tg:") and k["plan"] != "internal"]
    api_stats = {
        "customer_keys_active": sum(1 for k in keys if k["active"]),
        "by_plan": {p: sum(1 for k in keys if k["active"] and k["plan"] == p) for p in auth.PLANS},
        "mrr_usd": sum(auth.PLANS[k["plan"]]["price_usd_month"] for k in keys if k["active"]),
    }
    with _api() as c:
        api_stats["requests_today"] = _one(c, "SELECT SUM(count) FROM usage WHERE day = ?", (store.today(),))
        api_stats["requests_30d"] = _one(c, "SELECT SUM(count) FROM usage WHERE day >= ?", (store.today(-30),))
        daily = _rows(c, "SELECT day, SUM(count) AS requests FROM usage WHERE day >= ? GROUP BY day ORDER BY day",
                      (store.today(-30),))
    with _bot() as b:
        signups = _rows(b, "SELECT SUBSTR(first_seen, 1, 10) AS day, COUNT(*) AS users FROM users "
                           "WHERE first_seen >= ? GROUP BY SUBSTR(first_seen, 1, 10) ORDER BY day", (store.ago(30),))
        stars = _rows(b, "SELECT SUBSTR(created_at, 1, 10) AS day, SUM(stars) AS stars FROM payments WHERE refunded=0 "
                         "AND created_at >= ? GROUP BY SUBSTR(created_at, 1, 10) ORDER BY day", (store.ago(30),))
    return {"bot": bot, "api": api_stats, "series": {"requests": daily, "signups": signups, "stars": stars},
            "premium_price_stars": int(os.environ.get("PREMIUM_STARS", "150"))}


@api.get("/users")
def users(search: str = "", limit: int = 100, offset: int = 0):
    needle = search.strip().lstrip('@').lower()
    like = f"%{needle}%"
    with _bot() as b:
        rows = _rows(b, """
            SELECT u.user_id, u.username, u.first_name, u.last_name, u.language, u.first_seen, u.last_seen, u.actions,
                   COALESCE(s.units, 'metric') AS units, p.until AS premium_until,
                   (SELECT COUNT(*) FROM user_favorites f WHERE f.user_id = u.user_id) AS favorites,
                   sub.city AS daily_city, ak.plan AS app_plan,
                   (SELECT COALESCE(SUM(stars),0) FROM payments pay WHERE pay.user_id=u.user_id AND refunded=0) AS stars_paid
            FROM users u
            LEFT JOIN user_settings s ON s.user_id = u.user_id
            LEFT JOIN premium p ON p.user_id = u.user_id
            LEFT JOIN user_subscriptions sub ON sub.user_id = u.user_id
            LEFT JOIN app_keys ak ON ak.user_id = u.user_id
            WHERE (? = '' OR CAST(u.user_id AS TEXT) LIKE ? OR LOWER(COALESCE(u.username, '')) LIKE ?
                   OR LOWER(COALESCE(u.first_name, '')) LIKE ? OR LOWER(COALESCE(u.last_name, '')) LIKE ?)
            ORDER BY COALESCE(u.last_seen, '') DESC LIMIT ? OFFSET ?""",
                     (needle, like, like, like, like, limit, offset))
        total = _one(b, "SELECT COUNT(*) FROM users")
    now = _now()
    for r in rows:
        r["premium"] = bool(r["premium_until"] and r["premium_until"] > now)
        r["premium_until"] = _iso(r["premium_until"])
    return {"total": total, "users": rows}


@api.get("/users/{uid}")
def user_detail(uid: int):
    with _bot() as b:
        return {
            "favorites": [r["city"] for r in _rows(b, "SELECT city FROM user_favorites WHERE user_id=?", (uid,))],
            "subscription": (_rows(b, "SELECT city, units FROM user_subscriptions WHERE user_id=?", (uid,)) or [None])[0],
            "payments": _rows(b, "SELECT charge_id, stars, until, refunded, created_at FROM payments WHERE user_id=? "
                                 "ORDER BY created_at DESC", (uid,)),
        }


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else None


def _sync_app_key(uid: int, premium: bool):
    plan = "premium" if premium else "app_free"
    for k in auth.list_keys():
        if k["name"] == f"tg:{uid}" and k["active"]:
            auth.set_plan(k["id"], plan)
    with _bot() as b:
        b.execute("UPDATE app_keys SET plan=? WHERE user_id=?", (plan, uid))


@api.post("/users/{uid}/premium")
def grant_premium(uid: int, days: int = 30):
    with _bot() as b:
        row = b.execute("SELECT until FROM premium WHERE user_id=?", (uid,)).fetchone()
        start = max(row[0] or 0, _now()) if row else _now()
        until = start + days * 86400
        b.execute("INSERT INTO premium(user_id, until, charge_id, recurring, updated_at) VALUES (?,?,?,0,?) "
                  "ON CONFLICT(user_id) DO UPDATE SET until=excluded.until, charge_id=excluded.charge_id, "
                  "recurring=0, updated_at=excluded.updated_at", (uid, until, f"manual-{_now()}", store.now()))
        b.execute("INSERT INTO payments(charge_id, user_id, stars, until, created_at) VALUES (?,?,0,?,?)",
                  (f"manual-{_now()}-{uid}", uid, until, store.now()))
    _sync_app_key(uid, True)
    return {"user_id": uid, "premium_until": _iso(until)}


@api.post("/users/{uid}/premium/remove")
def remove_premium(uid: int):
    with _bot() as b:
        b.execute("UPDATE premium SET until=? WHERE user_id=?", (_now(), uid))
    _sync_app_key(uid, False)
    return {"user_id": uid, "premium": False}


@api.get("/payments")
def payments(limit: int = 200):
    with _bot() as b:
        rows = _rows(b, """SELECT p.charge_id, p.user_id, u.username, u.first_name, p.stars, p.until, p.refunded, p.created_at
                           FROM payments p LEFT JOIN users u ON u.user_id = p.user_id
                           ORDER BY p.created_at DESC LIMIT ?""", (limit,))
    for r in rows:
        r["until"] = _iso(r["until"])
        r["manual"] = r["charge_id"].startswith("manual-")
    return {"payments": rows}


@api.post("/payments/{charge_id}/refund")
def refund(charge_id: str):
    with _bot() as b:
        row = b.execute("SELECT user_id, refunded FROM payments WHERE charge_id=?", (charge_id,)).fetchone()
    if not row:
        raise forecast.NotFound("Payment not found")
    if row["refunded"]:
        return {"refunded": True, "note": "already refunded"}
    if not charge_id.startswith("manual-"):
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        r = requests.post(f"https://api.telegram.org/bot{token}/refundStarPayment",
                          data={"user_id": row["user_id"], "telegram_payment_charge_id": charge_id}, timeout=30)
        body = r.json()
        if not body.get("ok"):
            raise auth.AuthError(400, f"Telegram refused the refund: {body.get('description')}")
    with _bot() as b:
        b.execute("UPDATE payments SET refunded=1 WHERE charge_id=?", (charge_id,))
        b.execute("UPDATE premium SET until=? WHERE user_id=?", (_now(), row["user_id"]))
    _sync_app_key(row["user_id"], False)
    return {"refunded": True}


@api.get("/keys")
def keys():
    with _api() as c:
        usage_today = {r["key_id"]: r["n"] for r in _rows(c, "SELECT key_id, SUM(count) AS n FROM usage WHERE day=? GROUP BY key_id", (store.today(),))}
        usage_30 = {r["key_id"]: r["n"] for r in _rows(c, "SELECT key_id, SUM(count) AS n FROM usage WHERE day>=? GROUP BY key_id", (store.today(-30),))}
    out = []
    for k in auth.list_keys():
        k["requests_today"] = usage_today.get(k["id"], 0)
        k["requests_30d"] = usage_30.get(k["id"], 0)
        k["kind"] = "app user" if k["name"].startswith("tg:") else ("internal" if k["plan"] == "internal" else "customer")
        out.append(k)
    return {"keys": out, "plans": auth.PLANS}


@api.post("/keys")
def create_key(name: str, plan: str = "free"):
    try:
        return {"api_key": auth.create_key(name, plan)}
    except ValueError as e:
        raise auth.AuthError(400, str(e))


@api.post("/keys/{key_id}/plan")
def key_plan(key_id: int, plan: str):
    try:
        auth.set_plan(key_id, plan)
    except ValueError as e:
        raise auth.AuthError(400, str(e))
    return {"ok": True}


@api.post("/keys/{key_id}/active")
def key_active(key_id: int, active: bool):
    auth.set_active(key_id, active)
    return {"ok": True}


@api.get("/data")
def data():
    local = db.connect()
    health = [dict(r) for r in local.execute("SELECT * FROM source_health ORDER BY source")]
    runs = [dict(r) for r in local.execute("SELECT model, run, status, finished_at, error FROM runs ORDER BY run DESC LIMIT 12")]
    return {"status": forecast.status(), "sources": health, "runs": runs}


router.include_router(api)
