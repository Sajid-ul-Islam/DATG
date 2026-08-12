import logging
from fastapi import FastAPI, Request, Response, HTTPException
from telegram import Update
from telegram.ext import Application
from bot.config import TELEGRAM_BOT_TOKEN, WEBHOOK_URL, TELEGRAM_WEBHOOK_SECRET
from bot.handlers import get_bot_handlers

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

fastapi_app = FastAPI(title="Telegram Data Analysis Bot API")

# Lazy-loaded Application instance
bot_app: Application = None


async def get_telegram_app() -> Application:
    """
    Initializes and initializes python-telegram-bot application for webhook handling.
    """
    global bot_app
    if bot_app is None:
        if not TELEGRAM_BOT_TOKEN:
            raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not configured.")

        bot_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        for handler in get_bot_handlers():
            bot_app.add_handler(handler)
        await bot_app.initialize()
    return bot_app


@fastapi_app.get("/")
async def root():
    return {
        "status": "online",
        "service": "Telegram Data Analysis Bot",
        "instructions": "Upload CSV/Excel files to your Telegram Bot.",
        "endpoints": {
            "health": "/api/health",
            "set_webhook": "/api/set_webhook",
            "webhook": "/api/webhook"
        }
    }


@fastapi_app.get("/health")
@fastapi_app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "Telegram Data Analysis Bot"}


def _check_secret_header(request: Request) -> bool:
    """
    Verify Telegram's `X-Telegram-Bot-Api-Secret-Token` header.

    Returns True when no secret is configured (opt-in hardening), or when the
    header matches. Used to reject spoofed requests that never came from
    Telegram.
    """
    if not TELEGRAM_WEBHOOK_SECRET:
        return True
    return request.headers.get("X-Telegram-Bot-Api-Secret-Token") == TELEGRAM_WEBHOOK_SECRET


@fastapi_app.post("/webhook")
@fastapi_app.post("/api/webhook")
async def telegram_webhook(request: Request):
    """
    Receives Webhook updates from Telegram API.
    """
    if not _check_secret_header(request):
        return Response(content="Forbidden: invalid webhook secret", status_code=403)
    try:
        data = await request.json()
        app = await get_telegram_app()
        update = Update.de_json(data, app.bot)
        if update:
            await app.process_update(update)
        return Response(content="OK", status_code=200)
    except Exception as e:
        logger.exception("Error processing webhook update")
        return Response(content=str(e), status_code=500)


@fastapi_app.get("/set_webhook")
@fastapi_app.get("/api/set_webhook")
async def set_webhook():
    """
    Helper endpoint to trigger setWebhook call to Telegram API.
    """
    if not TELEGRAM_BOT_TOKEN or not WEBHOOK_URL:
        raise HTTPException(
            status_code=400,
            detail="TELEGRAM_BOT_TOKEN and WEBHOOK_URL environment variables must be configured in Vercel settings."
        )

    app = await get_telegram_app()
    success = await app.bot.set_webhook(
        url=WEBHOOK_URL,
        secret_token=TELEGRAM_WEBHOOK_SECRET or None,
        drop_pending_updates=True,
    )
    if success:
        msg = f"Webhook set successfully to {WEBHOOK_URL}"
        if TELEGRAM_WEBHOOK_SECRET:
            msg += " (secret token enabled)"
            logger.info(
                "Webhook secret configured — Telegram will now require the "
                "X-Telegram-Bot-Api-Secret-Token header on every update."
            )
        return {"status": "success", "message": msg}
    else:
        raise HTTPException(status_code=500, detail="Failed to set webhook with Telegram API.")


# Expose FastAPI application as `app` for Vercel
app = fastapi_app

