import atexit
import logging
import os
import subprocess
import sys
import threading
import time

from . import grids, ingest, observations
from .config import INGEST_CHECK_MINUTES, INGEST_ENABLED, MODELS, OBS_CHECK_MINUTES, ROOT

log = logging.getLogger("skymate.scheduler")
_started = False
_worker: subprocess.Popen | None = None


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


def run_heavy_loops():
    """Entry point of the worker process: forecast ingest (and history backfill) threads."""
    loops = [(_forecast_loop, "forecast")]
    if os.environ.get("SKYMATE_OBS_BACKFILL", "1") == "1":
        loops.append((_obs_history_loop, "obs-history"))
    threads = [threading.Thread(target=t, name=f"skymate-{n}", daemon=True) for t, n in loops]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def _supervise_worker():
    """Keeps the worker process alive; restarts it if it exits."""
    global _worker
    delay = 5
    while True:
        _worker = subprocess.Popen([sys.executable, "-m", "skymate_api.worker"], cwd=ROOT)
        log.info("Background worker started (pid %s)", _worker.pid)
        started = time.time()
        code = _worker.wait()
        delay = 5 if time.time() - started > 300 else min(delay * 2, 120)
        log.warning("Background worker exited with %s; restarting in %ss", code, delay)
        time.sleep(delay)


def _stop_worker():
    if _worker and _worker.poll() is None:
        _worker.terminate()


def start():
    global _started
    if _started or not INGEST_ENABLED:
        if not INGEST_ENABLED:
            log.info("Ingest disabled (SKYMATE_INGEST=0); serving stored data only")
        return
    _started = True
    # Light, network-bound collection stays in the web process; heavy decoding runs in a niced worker.
    threading.Thread(target=_obs_loop, name="skymate-observations", daemon=True).start()
    threading.Thread(target=_supervise_worker, name="skymate-worker-supervisor", daemon=True).start()
    atexit.register(_stop_worker)
    log.info("Scheduler started (models: %s every %d min, observations every %d min)",
             ", ".join(MODELS), INGEST_CHECK_MINUTES, OBS_CHECK_MINUTES)
