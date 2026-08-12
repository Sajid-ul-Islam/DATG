import logging
import os
import re
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
PORT = int(os.getenv("PORT", "8000"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
DATABASE_PATH = os.getenv("DATABASE_PATH", "bot_sessions.db")
BLOB_READ_WRITE_TOKEN = os.getenv("BLOB_READ_WRITE_TOKEN", "")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")

# Telegram only allows A-Z, a-z, 0-9, `_` and `-` in the webhook secret token.
# An invalid secret makes setWebhook fail (HTTP 500), which would block webhook
# registration and lock the bot out of updates. Treat it as unset instead so
# the webhook can always be registered (hardening is simply disabled).
if TELEGRAM_WEBHOOK_SECRET and not re.fullmatch(r"[A-Za-z0-9_-]+", TELEGRAM_WEBHOOK_SECRET):
    logger.warning(
        "TELEGRAM_WEBHOOK_SECRET contains characters Telegram does not allow "
        "(only A-Z, a-z, 0-9, _ and -). Ignoring it — the webhook will be "
        "registered without a secret."
    )
    TELEGRAM_WEBHOOK_SECRET = ""
