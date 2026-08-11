import logging
import io
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters
from bot.analyzer import DataAnalyzer

logger = logging.getLogger(__name__)

MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB Telegram limit


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    `/start` command handler.
    """
    welcome_text = (
        "📊 **Welcome to Telegram Data Analysis Bot!**\n\n"
        "Send me any **CSV** (`.csv`) or **Excel** (`.xlsx`, `.xls`) dataset, and I will analyze it instantly:\n"
        "• 📈 **Summary Metrics** (rows, columns, data types, missing values)\n"
        "• 📊 **Descriptive Statistics** (mean, median, standard deviation)\n"
        "• 🖼️ **Visual Charts** (distribution plots, correlation heatmaps, categorical charts)\n\n"
        "👇 Simply drag & drop or upload your file to get started!"
    )
    if update.message:
        await update.message.reply_text(welcome_text, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    `/help` command handler.
    """
    help_text = (
        "💡 **How to Use:**\n\n"
        "1. Attach a `.csv`, `.xlsx`, or `.xls` file in this chat.\n"
        "2. Wait a few seconds while the bot analyzes your data.\n"
        "3. View the generated metrics summary and high-resolution chart images.\n\n"
        "⚠️ **File Size Limit:** Files up to 20MB are supported."
    )
    if update.message:
        await update.message.reply_text(help_text, parse_mode="Markdown")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Document upload update handler.
    """
    if not update.message or not update.message.document:
        return

    doc = update.message.document
    filename = doc.file_name or "uploaded_file.csv"

    # Validate file extension
    if not filename.lower().endswith(('.csv', '.xlsx', '.xls')):
        await update.message.reply_text(
            "⚠️ Unsupported file type. Please send a `.csv`, `.xlsx`, or `.xls` file.",
            parse_mode="Markdown"
        )
        return

    # Validate file size
    if doc.file_size and doc.file_size > MAX_FILE_SIZE_BYTES:
        await update.message.reply_text(
            "❌ File size exceeds the 20MB limit. Please upload a smaller file.",
            parse_mode="Markdown"
        )
        return

    status_msg = await update.message.reply_text("⏳ Processing your dataset... Please wait.")

    try:
        # Download document file bytes
        file_obj = await doc.get_file()
        file_bytes = await file_obj.download_as_bytearray()

        # Load DataFrame
        df = DataAnalyzer.load_dataframe(bytes(file_bytes), filename)

        # Generate summary text
        summary_text = DataAnalyzer.generate_summary(df, filename)
        await update.message.reply_text(summary_text, parse_mode="Markdown")

        # Generate and send chart images
        charts = DataAnalyzer.generate_visualizations(df)
        for chart_buf, caption in charts:
            chart_buf.seek(0)
            await update.message.reply_photo(photo=chart_buf, caption=caption)

    except Exception as e:
        logger.exception("Error processing document %s", filename)
        await update.message.reply_text(
            f"❌ **Error processing file:** {str(e)}",
            parse_mode="Markdown"
        )

    finally:
        # Delete temporary status message if possible
        try:
            await status_msg.delete()
        except Exception:
            pass


def get_bot_handlers():
    """
    Returns list of configured handlers for the python-telegram-bot application.
    """
    return [
        CommandHandler("start", start_command),
        CommandHandler("help", help_command),
        MessageHandler(filters.Document.ALL, handle_document),
    ]
