import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"


def load_env(path: Path = ENV_FILE):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def set_env_value(key: str, value: str, path: Path = ENV_FILE):
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = [l for l in lines if not l.strip().startswith(f"{key}=")]
    lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value


load_env()

DATA_DIR = Path(os.environ.get("SKYMATE_DATA_DIR", ROOT / "data"))
GRID_DIR = DATA_DIR / "grids"
HISTORY_DIR = DATA_DIR / "history"
STATIC_DIR = DATA_DIR / "static"
DB_PATH = DATA_DIR / "skymate.db"
LOG_DIR = ROOT / "logs"

for d in (DATA_DIR, GRID_DIR, HISTORY_DIR, STATIC_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)

API_HOST = os.environ.get("SKYMATE_API_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("SKYMATE_API_PORT", "8000"))
ADMIN_TOKEN = os.environ.get("SKYMATE_ADMIN_TOKEN", "")

# Models to ingest, in order of preference when both have equally fresh data.
MODELS = [m.strip() for m in os.environ.get("SKYMATE_MODELS", "ecmwf,gfs").split(",") if m.strip()]
FORECAST_HOURS = int(os.environ.get("SKYMATE_FORECAST_HOURS", "240"))
RUNS_TO_KEEP = int(os.environ.get("SKYMATE_RUNS_TO_KEEP", "2"))
HISTORY_DAYS = int(os.environ.get("SKYMATE_HISTORY_DAYS", "365"))
INGEST_ENABLED = os.environ.get("SKYMATE_INGEST", "1") == "1"
INGEST_CHECK_MINUTES =int(os.environ.get("SKYMATE_INGEST_CHECK_MINUTES", "30"))
DOWNLOAD_WORKERS = int(os.environ.get("SKYMATE_DOWNLOAD_WORKERS", "4"))

# Last-resort live providers, used only when no stored grid covers a request.
OPENWEATHER_KEY = os.environ.get("WEATHER_TOKEN", "")
ENABLE_LIVE_FALLBACK = os.environ.get("SKYMATE_LIVE_FALLBACK", "1") == "1"

# Grid every model is resampled onto: 0.5 degree, lat 90..-90, lon 0..359.5
GRID_RES = 0.5
GRID_NLAT = 361
GRID_NLON = 720
