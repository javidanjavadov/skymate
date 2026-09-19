import logging
import threading
import time

from . import grids, ingest
from .config import INGEST_CHECK_MINUTES, INGEST_ENABLED, MODELS

log = logging.getLogger("skymate.scheduler")
_started = False


def _loop():
    try:
        ingest.backfill_history(days=7)
    except Exception:
        log.exception("History backfill failed")
    while True:
        for model in MODELS:
            try:
                ingest.ingest_latest(model)
            except Exception:
                log.exception("Ingest cycle failed for %s", model)
            try:
                grids.cleanup(model)
            except Exception:
                log.exception("Cleanup failed for %s", model)
        time.sleep(INGEST_CHECK_MINUTES * 60)


def start():
    global _started
    if _started or not INGEST_ENABLED:
        if not INGEST_ENABLED:
            log.info("Ingest disabled (SKYMATE_INGEST=0); serving stored data only")
        return
    _started = True
    threading.Thread(target=_loop, name="skymate-ingest", daemon=True).start()
    log.info("Ingest scheduler started (models: %s, every %d min)", ", ".join(MODELS), INGEST_CHECK_MINUTES)
