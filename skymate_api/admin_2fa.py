"""Second sign-in step for the owner console: a one-time code sent to the owner's Telegram.

The admin token alone only starts a sign-in. The console works with a short-lived session that is issued after the
owner types the code the bot sent them, so a leaked token is not enough to get in.
Set SKYMATE_ADMIN_2FA=0 to turn this off (local development only).
"""
import hashlib
import logging
import os
import secrets
import threading
import time

import requests

from . import security

log = logging.getLogger("skymate.admin")

ENABLED = os.environ.get("SKYMATE_ADMIN_2FA", "1") != "0"
CODE_SECONDS = 300          # a code is valid for 5 minutes
CODE_ATTEMPTS = 5           # wrong guesses before the code is thrown away
RESEND_SECONDS = 30         # at most one new code every 30 s
SESSION_IDLE_SECONDS = 1800  # sessions end after 30 minutes without use
SESSION_MAX_SECONDS = 12 * 3600

_lock = threading.Lock()
_code: dict | None = None   # only the owner signs in, so one pending code at a time
_last_sent = 0.0
_sessions: dict[str, dict] = {}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _send_telegram(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    owner = os.environ.get("BOT_ADMIN_ID", "")
    if not (token and owner):
        log.error("Admin sign-in code not sent: TELEGRAM_BOT_TOKEN or BOT_ADMIN_ID is not set")
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": int(owner), "text": text}, timeout=10)
        return r.ok
    except (requests.RequestException, ValueError):
        log.exception("Admin sign-in code could not be sent")
        return False


def start(ip: str) -> tuple[bool, str]:
    """Creates a code and sends it to the owner. Returns (ok, message for the console)."""
    global _code, _last_sent
    now = time.monotonic()
    with _lock:
        if now - _last_sent < RESEND_SECONDS and _code:
            return True, "A code was sent a moment ago. Check Telegram."
        code = f"{secrets.randbelow(1_000_000):06d}"
        _code = {"hash": _hash(code), "expires": now + CODE_SECONDS, "attempts": 0}
        _last_sent = now
    sent = _send_telegram(f"🔐 SkyMate console sign-in code: {code}\n\nValid for 5 minutes. Requested from {ip}.\n"
                          "If this wasn't you, change SKYMATE_ADMIN_TOKEN on Render now.")
    if not sent:
        with _lock:
            _code = None
        return False, "The code couldn't be sent to Telegram. Check BOT_ADMIN_ID and the bot token on the server."
    security.audit(ip, "admin_code_sent", "")
    return True, "We sent a 6-digit code to your Telegram."


def verify(ip: str, code: str) -> str | None:
    """Checks the code; on success returns a new session token."""
    global _code
    now = time.monotonic()
    session = None
    with _lock:
        pending = _code
        if not pending or now > pending["expires"]:
            _code = None
        elif secrets.compare_digest(_hash(code.strip()), pending["hash"]):
            _code = None
            session = secrets.token_urlsafe(32)
            _sessions[_hash(session)] = {"created": now, "used": now}
        else:
            pending["attempts"] += 1
            if pending["attempts"] >= CODE_ATTEMPTS:
                _code = None
    if session is None:
        security.record_admin_failure(ip, "admin_code_failed")
        return None
    security.audit(ip, "admin_login", "")
    return session


def check(session: str | None) -> bool:
    if not ENABLED:
        return True
    if not session:
        return False
    now = time.monotonic()
    key = _hash(session)
    with _lock:
        s = _sessions.get(key)
        if not s or now - s["used"] > SESSION_IDLE_SECONDS or now - s["created"] > SESSION_MAX_SECONDS:
            _sessions.pop(key, None)
            return False
        s["used"] = now
        return True


def end(session: str | None):
    if session:
        with _lock:
            _sessions.pop(_hash(session), None)
