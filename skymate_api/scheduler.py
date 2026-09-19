import logging
import os
import threading
import time

from . import grids, ingest, observations
from .config import INGEST_CHECK_MINUTES, INGEST_ENABLED, MODELS, OBS_CHECK_MINUTES

log = logging.getLogger("skymate.scheduler")
_started = False


def _forecast_loop():
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


def _obs_loop():
    last_station_refresh = 0.0
    while True:
        if time.time() - last_station_refresh > 24 * 3600:
            try:
                observations.refresh_official_stations()
                observations.refresh_airport_stations()
                last_station_refresh = time.time()
            except Exception:
                log.exception("Station list refresh failed")
        try:
            observations.collect_all()
        except Exception:
            log.exception("Observation collection failed")
        time.sleep(OBS_CHECK_MINUTES * 60)


def _obs_history_loop():
    while True:
        for job in (observations.backfill_isd, observations.fill_recent_synop):
            try:
                job()
            except Exception:
                log.exception("Observation history job %s failed", job.__name__)
        time.sleep(24 * 3600)


def start():
    global _started
    if _started or not INGEST_ENABLED:
        if not INGEST_ENABLED:
            log.info("Ingest disabled (SKYMATE_INGEST=0); serving stored data only")
        return
    _started = True
    loops = [(_forecast_loop, "forecast"), (_obs_loop, "observations")]
    if os.environ.get("SKYMATE_OBS_BACKFILL", "1") == "1":
        loops.append((_obs_history_loop, "obs-history"))
    for target, name in loops:
        threading.Thread(target=target, name=f"skymate-{name}", daemon=True).start()
    log.info("Scheduler started (models: %s every %d min, observations every %d min)",
             ", ".join(MODELS), INGEST_CHECK_MINUTES, OBS_CHECK_MINUTES)
