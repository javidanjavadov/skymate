import logging

import uvicorn

from .config import API_HOST, API_PORT

logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s %(message)s", level=logging.INFO)

if __name__ == "__main__":
    uvicorn.run("skymate_api.server:app", host=API_HOST, port=API_PORT, log_level="info")
