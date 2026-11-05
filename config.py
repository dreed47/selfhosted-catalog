"""Environment configuration. Other modules import constants from here."""
import os

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()
APP_PORT = int(os.getenv("APP_PORT", "5010"))
TZ_NAME = os.getenv("TZ", "America/New_York")

# Monday 08:00 in TZ. Reddit's newest megathread stays open until the next one
# is posted; the job ingests every thread except that newest one.
PULL_WEEKDAY = int(os.getenv("PULL_WEEKDAY", "0"))  # Monday
PULL_HOUR = int(os.getenv("PULL_HOUR", "8"))
PULL_MINUTE = int(os.getenv("PULL_MINUTE", "0"))
# Daily main-page release posts. Earlier than the Monday thread pull.
FEED_HOUR = int(os.getenv("FEED_HOUR", "7"))
FEED_MINUTE = int(os.getenv("FEED_MINUTE", "0"))
RUN_ON_START = os.getenv("RUN_ON_START", "1").strip() == "1"

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.getenv("DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.getenv("DB_PATH", os.path.join(DATA_DIR, "data.db"))

ARCTIC_SHIFT_BASE = os.getenv(
    "ARCTIC_SHIFT_BASE", "https://arctic-shift.photon-reddit.com"
).rstrip("/")
REDDIT_BASE = os.getenv("REDDIT_BASE", "https://www.reddit.com").rstrip("/")
REQUEST_GAP_S = float(os.getenv("REQUEST_GAP_S", "1.2"))
HTTP_TIMEOUT_S = float(os.getenv("HTTP_TIMEOUT_S", "45"))

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_GAP_S = float(os.getenv("GITHUB_GAP_S", "0.25" if GITHUB_TOKEN else "1.0"))

USER_AGENT = os.getenv(
    "USER_AGENT",
    "selfhosted-catalog/1.0 (self-hosted; weekly r/selfhosted catalog)",
)

PAGE_SIZE = int(os.getenv("PAGE_SIZE", "24"))
