"""Central configuration — everything overridable via environment variables."""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- Database ---------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'data', 'mlplay.db')}"
IS_POSTGRES = DATABASE_URL.startswith("postgres")

# --- App ---------------------------------------------------------------------
PORT = int(os.getenv("PORT", "8000"))
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
DEBUG_WEBAPP_DEV = os.getenv("DEBUG_WEBAPP_DEV", "0") == "1"

# --- Media / data paths -------------------------------------------------------
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
FONTS_DIR = os.path.join(DATA_DIR, "fonts")

for _d in (
    UPLOADS_DIR,
    os.path.join(UPLOADS_DIR, "receipts"),
    os.path.join(UPLOADS_DIR, "heroes"),
    os.path.join(UPLOADS_DIR, "logo"),
    os.path.join(UPLOADS_DIR, "promo"),
    os.path.join(UPLOADS_DIR, "broadcast"),
    FONTS_DIR,
):
    os.makedirs(_d, exist_ok=True)

MEDIA_PREFIX = "/media"

# --- Bot ---------------------------------------------------------------------
START_UP_BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()  # optional; admin panel can set it later

# match cadence (seconds) — every 2 minutes a new Rank Game match
MATCH_INTERVAL = 120
MATCH_BET_WINDOW = 105  # seconds during which bets are accepted
FIGHT_DURATION = 10     # seconds of "fighting" animation before the result

MIN_BET = 1
MAX_BET_GLOBAL = 50_000