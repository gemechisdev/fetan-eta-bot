import os

try:
    # Makes `python main.py` / `python run_polling.py` pick up a local .env
    # automatically. No-ops safely if python-dotenv isn't installed or
    # there's no .env file (e.g. on Vercel/Docker where env vars are
    # injected by the platform instead).
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

BOT_TOKEN = os.environ["BOT_TOKEN"]
MONGO_URI = os.environ["MONGO_URI"]
MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "fetan_eta")

# How long to wait for MongoDB to respond before giving up. Bump this via
# .env if you're on a slow/VPN'd connection (e.g. WSL) and see
# "No replica set members found yet" even though the DB is actually fine.
MONGO_TIMEOUT_MS = int(os.environ.get("MONGO_TIMEOUT_MS", "20000"))

# Comma separated telegram user ids, e.g. "111111111,222222222"
ADMIN_IDS = {
    int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()
}

# Used to validate that webhook calls really come from Telegram.
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

# Path the webhook server listens on (only used in webhook mode).
WEBHOOK_PATH = os.environ.get("WEBHOOK_PATH", "/webhook")

# Public base URL of this deployment, e.g. https://your-app.onrender.com
# When set, the webhook server auto-registers itself with Telegram on
# startup. Not needed in polling mode, and not used by api/webhook.py on
# Vercel (register that one with set_webhook.py instead, since serverless
# functions have no startup hook to run code at deploy time).
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").strip()

# Port the webhook server binds to. Most PaaS platforms (Render, Railway,
# Fly, Heroku, Cloud Run...) inject this automatically for web services.
PORT = int(os.environ.get("PORT", 8080))

# How many minutes to reserve a number while awaiting payment proof
# If a pending reservation is older than this it will be released
RESERVATION_TTL_MINUTES = int(os.environ.get("RESERVATION_TTL_MINUTES", "20"))

# Optional Telegram message effect id for final result announcements.
# Defaults to Telegram's 🎉 animated effect when not set explicitly.
RESULT_MESSAGE_EFFECT_ID = os.environ.get("RESULT_MESSAGE_EFFECT_ID", "5298766204649872471").strip()

# RUN_MODE controls how main.py / app.py / bot.py behave:
#   "polling"  -> long-lived polling loop, no public URL/port needed
#   "webhook"  -> starts an HTTP server (aiohttp) with health/ping routes
#                 and an aiogram webhook endpoint
# If not set explicitly, we guess from the environment: platforms that run
# web services usually inject PORT, so its presence is a reasonable signal
# to default to webhook mode; otherwise polling is the simplest thing that
# works anywhere (VPS, systemd service, background worker, etc.).
_explicit_mode = os.environ.get("RUN_MODE", "").strip().lower()
if _explicit_mode in ("polling", "webhook"):
    RUN_MODE = _explicit_mode
else:
    RUN_MODE = "webhook" if os.environ.get("PORT") else "polling"