"""HTTP security: response headers, request IDs, per-IP limits, hidden admin access and the admin audit log."""
import hashlib
import logging
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque

from fastapi import Request

from . import store
from .config import ADMIN_TOKEN

log = logging.getLogger("skymate.security")


# ─── Hidden admin location ───────────────────────────────────────────────────

def admin_prefix(token: str) -> str:
    """Secret URL prefix for the admin panel, derived from the admin token (same logic in skymate_client)."""
    return "/console-" + hashlib.sha256(f"skymate-admin-path:{token}".encode()).hexdigest()[:24]


ADMIN_PREFIX = admin_prefix(ADMIN_TOKEN) if ADMIN_TOKEN else None


# ─── Response headers ────────────────────────────────────────────────────────

_BASE_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(self), camera=(), microphone=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}
_HTML_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
             "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
_DOCS_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
             "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
             "connect-src 'self'; frame-ancestors 'none'")


def apply_headers(request: Request, response):
    for k, v in _BASE_HEADERS.items():
        response.headers.setdefault(k, v)
    ctype = response.headers.get("content-type", "")
    if ctype.startswith("text/html"):
        path = request.url.path
        response.headers["Content-Security-Policy"] = _DOCS_CSP if path in ("/docs", "/redoc") else _HTML_CSP
        response.headers["Cache-Control"] = "no-store" if ADMIN_PREFIX and path.startswith(ADMIN_PREFIX) else \
            response.headers.get("Cache-Control", "no-cache")
    if request.url.path.startswith("/v1/") or (ADMIN_PREFIX and request.url.path.startswith(ADMIN_PREFIX)):
        response.headers.setdefault("Cache-Control", "no-store")
    response.headers["X-Request-ID"] = request.state.request_id


def new_request_id(request: Request):
    incoming = request.headers.get("x-request-id", "")
    request.state.request_id = incoming if 8 <= len(incoming) <= 64 and incoming.isalnum() else uuid.uuid4().hex


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# ─── Per-IP limits ───────────────────────────────────────────────────────────

class SlidingWindow:
    def __init__(self, limit: int, seconds: int):
        self.limit, self.seconds = limit, seconds
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > self.seconds:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            if len(self.hits) > 50_000:
                for k in [k for k, v in self.hits.items() if not v][:10_000]:
                    del self.hits[k]
            return True


public_limiter = SlidingWindow(120, 60)       # unauthenticated pages and /v1/status per IP
invalid_key_limiter = SlidingWindow(30, 300)  # wrong API keys per IP


# ─── Admin authentication with lockout ───────────────────────────────────────

_admin_failures: dict[str, deque] = defaultdict(deque)
_admin_lock = threading.Lock()
ADMIN_MAX_FAILURES = 5
ADMIN_LOCK_SECONDS = 900


def admin_locked(ip: str) -> bool:
    now = time.monotonic()
    with _admin_lock:
        q = _admin_failures[ip]
        while q and now - q[0] > ADMIN_LOCK_SECONDS:
            q.popleft()
        return len(q) >= ADMIN_MAX_FAILURES


def check_admin_token(ip: str, token: str | None) -> bool:
    if not ADMIN_TOKEN or admin_locked(ip):
        return False
    if token and secrets.compare_digest(token, ADMIN_TOKEN):
        return True
    record_admin_failure(ip, "admin_auth_failed")
    return False


def record_admin_failure(ip: str, action: str):
    """Counts toward the lockout (wrong token or wrong Telegram code) and writes the audit log."""
    with _admin_lock:
        _admin_failures[ip].append(time.monotonic())
    log.warning("Rejected admin sign-in (%s) from %s", action, ip)
    audit(ip, action, "")


# ─── Audit log ───────────────────────────────────────────────────────────────

AUDIT_SCHEMA = ("CREATE TABLE IF NOT EXISTS admin_audit (at TEXT NOT NULL, ip TEXT, action TEXT NOT NULL, "
                "detail TEXT)")


def init_audit():
    with store.tx("api") as c:
        c.execute(AUDIT_SCHEMA)


def audit(ip: str, action: str, detail: str):
    try:
        with store.tx("api") as c:
            c.execute("INSERT INTO admin_audit(at, ip, action, detail) VALUES (?,?,?,?)",
                      (store.now(), ip, action, detail[:500]))
    except Exception:
        log.exception("Could not write audit entry")


def audit_entries(limit: int = 200) -> list[dict]:
    with store.tx("api") as c:
        rows = c.execute("SELECT at, ip, action, detail FROM admin_audit ORDER BY at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
