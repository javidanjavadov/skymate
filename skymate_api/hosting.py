"""Running inside a web host (Render): Telegram bot by webhook in this process, and keep-alive pings."""
import hashlib
import logging
import os
import secrets
import threading
import time

import requests
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

log = logging.getLogger("skymate.hosting")

BOT_MODE = os.environ.get("BOT_MODE", "")          # "webhook" = run the bot inside the API process
PUBLIC_URL = (os.environ.get("PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "").rstrip("/")
# Telegram only accepts [A-Za-z0-9_-] in secret tokens; hashing makes any generated value valid.
_raw_secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
WEBHOOK_SECRET = hashlib.sha256(_raw_secret.encode()).hexdigest() if _raw_secret else ""

router = APIRouter()
_ptb = None


async def start_bot():
    global _ptb
    if BOT_MODE != "webhook":
        return
    if not (PUBLIC_URL and WEBHOOK_SECRET and os.environ.get("TELEGRAM_BOT_TOKEN")):
        log.error("Webhook mode needs PUBLIC_URL/RENDER_EXTERNAL_URL, TELEGRAM_WEBHOOK_SECRET and TELEGRAM_BOT_TOKEN")
        return
    os.environ.setdefault("SKYMATE_API_URL", f"http://127.0.0.1:{os.environ.get('PORT', '8000')}")
    os.environ.setdefault("PUBLIC_API_URL", PUBLIC_URL)
    import bot as tgbot
    from telegram import Update

    _ptb = tgbot.build_app()
    await _ptb.initialize()
    await tgbot.restore_subscriptions(_ptb)
    await _ptb.start()
    await _ptb.bot.set_webhook(f"{PUBLIC_URL}/telegram/webhook", secret_token=WEBHOOK_SECRET,
                               allowed_updates=Update.ALL_TYPES)
    log.info("Telegram bot running by webhook at %s/telegram/webhook", PUBLIC_URL)


async def stop_bot():
    if _ptb:
        await _ptb.stop()
        await _ptb.shutdown()


@router.post("/telegram/webhook", include_in_schema=False)
async def telegram_webhook(request: Request, x_telegram_bot_api_secret_token: str | None = Header(None)):
    if not _ptb or not x_telegram_bot_api_secret_token or \
            not secrets.compare_digest(x_telegram_bot_api_secret_token, WEBHOOK_SECRET):
        return JSONResponse({"ok": False}, status_code=403)
    from telegram import Update
    await _ptb.update_queue.put(Update.de_json(await request.json(), _ptb.bot))
    return {"ok": True}


def start_keepalive(interval_minutes: int = 10):
    """Free web hosts sleep after ~15 idle minutes; a regular request to our own public URL prevents that."""
    if not PUBLIC_URL or os.environ.get("SKYMATE_KEEPALIVE", "1") != "1":
        return

    def loop():
        while True:
            time.sleep(interval_minutes * 60)
            try:
                requests.get(f"{PUBLIC_URL}/health", timeout=30)
            except requests.RequestException as e:
                log.warning("Keep-alive ping failed: %s", e)

    threading.Thread(target=loop, name="skymate-keepalive", daemon=True).start()
