"""Background worker for CPU-heavy jobs (forecast download and decoding, history backfills).

Runs as a separate low-priority process so web requests always get the CPU first.
Started by scheduler.start(); can also be run alone: python -m skymate_api.worker
"""
import logging
import os

from . import db, scheduler

logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s %(message)s", level=logging.INFO)


def main():
    if hasattr(os, "nice"):
        try:
            os.nice(15)
        except OSError:
            pass
    db.init()
    scheduler.run_heavy_loops()


if __name__ == "__main__":
    main()
