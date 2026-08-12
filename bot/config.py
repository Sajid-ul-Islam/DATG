import os
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
PORT = int(os.getenv("PORT", "8000"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
DATABASE_PATH = os.getenv("DATABASE_PATH", "bot_sessions.db")
BLOB_READ_WRITE_TOKEN = os.getenv("BLOB_READ_WRITE_TOKEN", "")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
