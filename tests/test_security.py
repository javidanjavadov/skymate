import os

import re

import pytest

from skymate_api import admin_2fa, auth, security

ADMIN = os.environ["SKYMATE_ADMIN_TOKEN"]
INTERNAL = os.environ["SKYMATE_API_KEY"]
PREFIX = security.admin_prefix(ADMIN)


@pytest.fixture()
def telegram(monkeypatch):
    """Captures the sign-in messages the bot would send to the owner."""
    sent = []
    monkeypatch.setattr(admin_2fa, "_send_telegram", lambda text: sent.append(text) or True)
    monkeypatch.setattr(admin_2fa, "_code", None)
    monkeypatch.setattr(admin_2fa, "_last_sent", 0.0)
    return sent


def sign_in(client, telegram) -> dict:
    """Full owner sign-in: token, then the code from Telegram. Returns headers for console calls."""
    h = {"X-Admin-Token": ADMIN}
    assert client.post(f"{PREFIX}/signin/start", headers=h).json()["twofa"] is True
    code = re.search(r"(\d{6})", telegram[-1]).group(1)
    r = client.post(f"{PREFIX}/signin/verify", params={"code": code}, headers=h)
    assert r.status_code == 200
    return {**h, "X-Admin-Session": r.json()["session"]}


def test_admin_is_not_at_obvious_paths(client):
    for path in ("/admin", "/admin/", "/admin/keys", "/admin/api/overview", "/console", "/owner", "/login"):
        r = client.get(path, headers={"X-Admin-Token": ADMIN})
        assert r.status_code == 404, path
        assert r.json()["error"]["code"] == "not_found"


def test_admin_requires_token_and_hides_itself(client, telegram):
    assert client.get(f"{PREFIX}/api/overview").status_code == 404
    assert client.get(f"{PREFIX}/api/overview", headers={"X-Admin-Token": "wrong"}).status_code == 404
    r = client.get(f"{PREFIX}/api/overview", headers=sign_in(client, telegram))
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "no-store"


def test_admin_locks_out_after_repeated_failures(client):
    for _ in range(security.ADMIN_MAX_FAILURES):
        client.get(f"{PREFIX}/api/overview", headers={"X-Admin-Token": "guess"})
    r = client.get(f"{PREFIX}/api/overview", headers={"X-Admin-Token": ADMIN})
    assert r.status_code == 404
    assert client.get(f"{PREFIX}/").status_code == 404
    entries = security.audit_entries()
    assert any(e["action"] == "admin_auth_failed" for e in entries)


def test_admin_actions_are_audited(client, telegram):
    h = sign_in(client, telegram)
    r = client.post(f"{PREFIX}/api/keys", params={"name": "Audit Co", "plan": "starter"}, headers=h)
    assert r.status_code == 200 and r.json()["api_key"].startswith("sk_")
    assert any(e["action"] == "key_created" and "Audit Co" in e["detail"] for e in security.audit_entries())


def test_admin_hidden_from_api_docs(client):
    spec = client.get("/openapi.json").text
    for word in ("console", "/admin", "telegram", "X-Admin-Token", "internal"):
        assert word not in spec, word


def test_api_key_only_accepted_in_header(client):
    assert client.get("/v1/me").status_code == 401
    assert client.get("/v1/me", params={"api_key": INTERNAL}).status_code == 401
    r = client.get("/v1/me", headers={"X-API-Key": INTERNAL})
    assert r.status_code == 200 and r.json()["plan"] == "internal"


def test_invalid_keys_get_rate_limited(client):
    codes = [client.get("/v1/me", headers={"X-API-Key": f"sk_bad{i}"}).status_code for i in range(35)]
    assert codes[0] == 401 and codes[-1] == 429


def test_security_headers(client):
    r = client.get("/")
    h = r.headers
    assert h["X-Frame-Options"] == "DENY"
    assert h["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in h["Content-Security-Policy"]
    assert "max-age" in h["Strict-Transport-Security"]
    assert len(h["X-Request-ID"]) >= 8
    assert "server" not in {k.lower() for k in h} or "uvicorn" not in h.get("server", "")


def test_errors_are_uniform_and_carry_request_id(client):
    r = client.get("/v1/current", headers={"X-API-Key": INTERNAL}, params={"lat": 100, "lon": 0})
    body = r.json()["error"]
    assert r.status_code == 422 and body["code"] == "invalid_request" and body["request_id"]
    r = client.get("/v1/current", headers={"X-API-Key": INTERNAL})
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_request"
    r = client.get("/v1/current", headers={"X-API-Key": INTERNAL}, params={"q": "x" * 101})
    assert r.status_code == 422


def test_bad_station_and_dates_are_rejected(client):
    h = {"X-API-Key": INTERNAL}
    assert client.get("/v1/observations/history", headers=h, params={"station": "'; DROP TABLE--"}).status_code == 400
    assert client.get("/v1/observations/history", headers=h,
                      params={"station": "UBBB", "start": "not-a-date"}).status_code == 400
    assert client.get("/v1/observations/history", headers=h,
                      params={"station": "UBBB", "start": "2020-01-01", "end": "2019-01-01"}).status_code == 400


def test_telegram_webhook_rejects_unknown_callers(client):
    assert client.post("/telegram/webhook", json={}).status_code == 404
    assert client.post("/telegram/webhook", json={},
                       headers={"X-Telegram-Bot-Api-Secret-Token": "guess"}).status_code == 404


def test_public_plans_hide_internal_tiers(client):
    plans = client.get("/v1/plans").json()["plans"]
    assert set(plans) == {"free", "starter", "pro", "business"}


def test_plan_limits():
    info = {"plan": "free"}
    auth.require(info, "max_forecast_days", 5)
    try:
        auth.require(info, "max_forecast_days", 10)
        raise AssertionError("free plan must not get 10 days")
    except auth.AuthError as e:
        assert e.status == 403


def test_token_alone_does_not_open_the_console(client, telegram):
    h = {"X-Admin-Token": ADMIN}
    assert client.get(f"{PREFIX}/api/overview", headers=h).status_code == 404
    assert client.get(f"{PREFIX}/api/overview", headers={**h, "X-Admin-Session": "made-up"}).status_code == 404
    assert client.post(f"{PREFIX}/signin/start", headers={"X-Admin-Token": "wrong"}).status_code == 404
    assert telegram == []


def test_wrong_codes_count_toward_lockout(client, telegram):
    h = {"X-Admin-Token": ADMIN}
    client.post(f"{PREFIX}/signin/start", headers=h)
    real = re.search(r"(\d{6})", telegram[-1]).group(1)
    wrong = "000000" if real != "000000" else "111111"
    for _ in range(security.ADMIN_MAX_FAILURES):
        assert client.post(f"{PREFIX}/signin/verify", params={"code": wrong}, headers=h).status_code == 404
    # Locked out now: even the right code and token are refused
    assert client.post(f"{PREFIX}/signin/verify", params={"code": real}, headers=h).status_code == 404
    assert any(e["action"] == "admin_code_failed" for e in security.audit_entries())


def test_code_is_single_use(client, telegram):
    h = {"X-Admin-Token": ADMIN}
    client.post(f"{PREFIX}/signin/start", headers=h)
    code = re.search(r"(\d{6})", telegram[-1]).group(1)
    assert client.post(f"{PREFIX}/signin/verify", params={"code": code}, headers=h).status_code == 200
    assert client.post(f"{PREFIX}/signin/verify", params={"code": code}, headers=h).status_code == 404


def test_sign_out_ends_the_session(client, telegram):
    h = sign_in(client, telegram)
    assert client.post(f"{PREFIX}/signin/end", headers=h).status_code == 200
    assert client.get(f"{PREFIX}/api/overview", headers=h).status_code == 404


def test_bot_service_route_is_limited_to_app_keys(client):
    h = {"X-Admin-Token": ADMIN}
    r = client.post(f"{PREFIX}/service/keys", params={"name": "tg:42", "plan": "app_free"}, headers=h)
    assert r.status_code == 200 and r.json()["api_key"].startswith("sk_")
    assert client.post(f"{PREFIX}/service/keys/by-name/tg:42/plan", params={"plan": "premium"}, headers=h).status_code == 200
    # No customer keys, no business plans, and nothing without the token
    assert client.post(f"{PREFIX}/service/keys", params={"name": "Acme", "plan": "app_free"}, headers=h).status_code == 400
    assert client.post(f"{PREFIX}/service/keys", params={"name": "tg:43", "plan": "business"}, headers=h).status_code == 400
    assert client.post(f"{PREFIX}/service/keys/by-name/Acme/revoke", headers=h).status_code == 400
    assert client.post(f"{PREFIX}/service/keys", params={"name": "tg:44"}).status_code == 404
    assert client.post(f"{PREFIX}/service/keys/by-name/tg:42/revoke", headers=h).json()["revoked"]
