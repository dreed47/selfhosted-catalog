import logging
import time

import config
from logbuf import BufferHandler


def _configure_logging():
    fmt = logging.Formatter(
        fmt="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S %z",
    )
    fmt.converter = time.localtime  # follows the TZ environment variable
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    buf = BufferHandler()
    buf.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))
    root.handlers.clear()
    root.addHandler(stream)
    root.addHandler(buf)


_configure_logging()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from models import init_db
from routes import router
from scheduler import start as start_scheduler

logger = logging.getLogger(__name__)


def create_app():
    app = FastAPI(title="Selfhosted", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.include_router(router)

    @app.on_event("startup")
    def _startup():
        init_db()
        start_scheduler()
        logger.info("Selfhosted catalog listening")

    return app


app = create_app()
