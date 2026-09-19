import os
import sys
import tempfile
from pathlib import Path

# Isolated configuration: set before any skymate_api import.
_tmp = Path(tempfile.mkdtemp(prefix="skymate-tests-"))
os.environ.update({
    "SKYMATE_DATA_DIR": str(_tmp / "data"),
    "SKYMATE_BOT_DB": str(_tmp / "bot.db"),
    "SKYMATE_ADMIN_TOKEN": "test-admin-token-0123456789",
    "SKYMATE_API_KEY": "test-internal-key-0123456789",
    "SKYMATE_INGEST": "0",
    "SKYMATE_LIVE_FALLBACK": "0",
    "DATABASE_URL": "",
    "BOT_MODE": "",
})
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from skymate_api import db, security, store  # noqa: E402
from skymate_api.server import app  # noqa: E402

db.init()
store.init("bot")
security.init_audit()


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_limits():
    security._admin_failures.clear()
    security.public_limiter.hits.clear()
    security.invalid_key_limiter.hits.clear()
    yield
