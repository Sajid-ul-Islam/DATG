import logging
import sys
from telegram.ext import Application
from bot.config import TELEGRAM_BOT_TOKEN
from bot.handlers import get_bot_handlers

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def main() -> None:
    """
    Main entry point for local polling execution.
    """
    if not TELEGRAM_BOT_TOKEN:
        logger.error(
            "TELEGRAM_BOT_TOKEN is missing! Please set TELEGRAM_BOT_TOKEN in your .env file or environment variables."
        )
        sys.exit(1)

    logger.info("Initializing Telegram Data Analysis Bot (Polling Mode)...")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Register handlers
    for handler in get_bot_handlers():
        app.add_handler(handler)

    logger.info("Bot started successfully! Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()

