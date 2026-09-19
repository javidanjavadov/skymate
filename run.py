"""SkyMate supervisor: starts the API and the Telegram bot and restarts them if they stop.

    py run.py            # API + bot
    py run.py --api-only
"""
import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from skymate_api import auth, db  # noqa: E402
from skymate_api.config import API_PORT, LOG_DIR, set_env_value  # noqa: E402

MAX_LOG_BYTES = 20 * 1024 * 1024


def ensure_secrets():
    db.init()
    if not os.environ.get("SKYMATE_ADMIN_TOKEN"):
        set_env_value("SKYMATE_ADMIN_TOKEN", secrets.token_urlsafe(32))
        print("Created SKYMATE_ADMIN_TOKEN in .env")
    if not os.environ.get("SKYMATE_API_KEY"):
        set_env_value("SKYMATE_API_KEY", auth.create_key("SkyMate internal (bot + app)", "internal"))
        print("Created internal SKYMATE_API_KEY in .env")


class Child:
    def __init__(self, name: str, cmd: list[str]):
        self.name, self.cmd = name, cmd
        self.proc: subprocess.Popen | None = None
        self.log = LOG_DIR / f"{name}.log"
        self.restarts = 0
        self.started_at = 0.0

    def start(self):
        if self.log.exists() and self.log.stat().st_size > MAX_LOG_BYTES:
            self.log.replace(self.log.with_suffix(".log.1"))
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        fh = open(self.log, "ab")
        self.proc = subprocess.Popen(self.cmd, cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT, env=env)
        self.started_at = time.time()
        print(f"[{time.strftime('%H:%M:%S')}] started {self.name} (pid {self.proc.pid}), log: {self.log}")

    def check(self):
        if self.proc and self.proc.poll() is None:
            if time.time() - self.started_at > 300:
                self.restarts = 0
            return
        code = self.proc.returncode if self.proc else None
        delay = min(60, 5 * 2 ** self.restarts)
        print(f"[{time.strftime('%H:%M:%S')}] {self.name} exited ({code}); restarting in {delay}s")
        time.sleep(delay)
        self.restarts += 1
        self.start()

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def wait_for_api(timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if requests.get(f"http://127.0.0.1:{API_PORT}/health", timeout=3).ok:
                return True
        except requests.RequestException:
            pass
        time.sleep(2)
    return False


def main():
    ensure_secrets()
    children = [Child("api", [sys.executable, "-m", "skymate_api"])]
    if "--api-only" not in sys.argv:
        children.append(Child("bot", [sys.executable, "bot.py"]))

    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    children[0].start()
    if not wait_for_api():
        print("API did not become healthy within 90s; continuing, supervisor will keep retrying.")
    for c in children[1:]:
        c.start()
    print(f"SkyMate running. API docs: http://127.0.0.1:{API_PORT}/docs  (Ctrl+C to stop)")
    try:
        while not stopping:
            for c in children:
                c.check()
            time.sleep(3)
    finally:
        for c in reversed(children):
            c.stop()
        print("SkyMate stopped.")


if __name__ == "__main__":
    main()
