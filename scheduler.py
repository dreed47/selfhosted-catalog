"""Monday morning pull. The web process stays up while this thread waits."""
import logging
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config

logger = logging.getLogger(__name__)

_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def next_run(now, weekday, hour, minute):
    """Next local time at hour:minute on weekday. `now` must be timezone-aware."""
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    delta_days = (weekday - candidate.weekday()) % 7
    candidate = candidate + timedelta(days=delta_days)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


def describe_schedule():
    name = _WEEKDAYS[config.PULL_WEEKDAY % 7]
    return f"{name} {config.PULL_HOUR:02d}:{config.PULL_MINUTE:02d} {config.TZ_NAME}"


def next_daily(now, hour, minute):
    """Next local time at hour:minute. `now` must be timezone-aware."""
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def start():
    weekly = threading.Thread(target=_weekly, name="weekly-pull", daemon=True)
    daily = threading.Thread(target=_daily, name="daily-feed", daemon=True)
    weekly.start()
    daily.start()
    return weekly


def _wait_until(when, tz):
    while True:
        remaining = (when - datetime.now(tz)).total_seconds()
        if remaining <= 0:
            return
        threading.Event().wait(min(30, remaining))


def _weekly():
    # Imported here so `next_run` can be tested without opening the database.
    import ingest

    tz = ZoneInfo(config.TZ_NAME)
    if config.RUN_ON_START:
        logger.info("Startup pull of closed megathreads and the main page")
        ingest.run_ingest(reason="startup")
    while True:
        now = datetime.now(tz)
        nxt = next_run(now, config.PULL_WEEKDAY, config.PULL_HOUR, config.PULL_MINUTE)
        logger.info("Next weekly pull at %s", nxt.strftime("%Y-%m-%d %H:%M %Z"))
        _wait_until(nxt, tz)
        ingest.run_ingest(reason="schedule")


def _daily():
    import ingest

    tz = ZoneInfo(config.TZ_NAME)
    while True:
        now = datetime.now(tz)
        nxt = next_daily(now, config.FEED_HOUR, config.FEED_MINUTE)
        logger.info("Next main-page pull at %s", nxt.strftime("%Y-%m-%d %H:%M %Z"))
        _wait_until(nxt, tz)
        ingest.ingest_feed(reason="schedule")
