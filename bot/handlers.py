import logging
import io
from typing import Optional
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters
from bot.analyzer import DataAnalyzer
from bot.config import OPENAI_API_KEY, DATABASE_PATH, BLOB_READ_WRITE_TOKEN
from bot.session_store import SessionStore
from bot.cloud_store import BlobSessionStore

logger = logging.getLogger(__name__)

MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB Telegram limit

# ──────────────────────────────────────────────────────────────────────────────
# Session helpers
# ──────────────────────────────────────────────────────────────────────────────

_store = None  # SQLite SessionStore or BlobSessionStore, chosen on first use


def _get_store():
    """
    Lazily create the session store for this deployment.

    Uses Vercel Blob when a `BLOB_READ_WRITE_TOKEN` is configured (persistent
    sessions on serverless deployments), otherwise falls back to the local
    SQLite store.
    """
    global _store
    if _store is None:
        if BLOB_READ_WRITE_TOKEN:
            logger.info("Using Vercel Blob session store (persistent sessions)")
            _store = BlobSessionStore()
        else:
            logger.info("Using SQLite session store (%s)", DATABASE_PATH)
            _store = SessionStore(DATABASE_PATH)
    return _store


def _user_id(update: Update) -> Optional[int]:
    """Return the effective user id, or None for channel/service updates."""
    user = update.effective_user
    return user.id if user else None


def _get_df(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Return (df, filename) from the session, or (None, None) if not set.

    Checks the in-memory cache first, then falls back to the session store
    (SQLite or Vercel Blob — so datasets survive restarts and cold starts).
    Restored datasets are re-cached.
    """
    user_id = _user_id(update)
    if user_id is None:
        return None, None

    # Fast path: already loaded in this process
    df = context.user_data.get("df")
    filename = context.user_data.get("filename")
    if df is not None:
        return df, filename

    # Durable source of truth: SQLite
    stored = _get_store().load(user_id)
    if stored is None:
        return None, None

    filename, data = stored
    try:
        df = DataAnalyzer.load_dataframe(data, filename)
    except Exception as e:
        logger.warning("Could not restore dataset for user %s: %s", user_id, e)
        return None, None

    context.user_data["df"] = df
    context.user_data["filename"] = filename
    return df, filename


async def _no_dataset_msg(update: Update) -> None:
    """Reply with a prompt to upload a file first."""
    if update.message:
        await update.message.reply_text(
            "📂 No dataset loaded yet.\n"
            "Please upload a `.csv`, `.xlsx`, or `.xls` file first.",
            parse_mode="Markdown",
        )


# ──────────────────────────────────────────────────────────────────────────────
# /start
# ──────────────────────────────────────────────────────────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/start` command handler."""
    welcome_text = (
        "📊 **Welcome to Telegram Data Analysis Bot!**\n\n"
        "Send me any **CSV** (`.csv`) or **Excel** (`.xlsx`, `.xls`) dataset, and I will analyze it instantly:\n"
        "• 📈 **Summary Metrics** (rows, columns, data types, missing values)\n"
        "• ⚠️ **Outlier Detection** (IQR method per numeric column)\n"
        "• 📊 **Visual Charts** (distributions, correlations, time-series)\n"
        "• 🤖 **AI Insights** (plain-English data summary — if configured)\n\n"
        "**Commands after uploading a file:**\n"
        "• `/preview [N]` — show first N rows (default 5)\n"
        "• `/columns` — list all columns with types & null counts\n"
        "• `/stats [col]` — per-column count/mean/min/max breakdown\n"
        "• `/sort <col> [asc|desc]` — reorder rows by a column\n"
        "• `/filter <col> <op> <val>` — filter rows (e.g. `/filter age > 30`)\n"
        "• `/export` — download the dataset as a cleaned CSV\n"
        "• `/help` — show this help again\n\n"
        "👇 Simply drag & drop or upload your file to get started!"
    )
    if update.message:
        await update.message.reply_text(welcome_text, parse_mode="Markdown")


# ──────────────────────────────────────────────────────────────────────────────
# /help
# ──────────────────────────────────────────────────────────────────────────────

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/help` command handler."""
    help_text = (
        "💡 **How to Use:**\n\n"
        "1. Attach a `.csv`, `.xlsx`, or `.xls` file in this chat.\n"
        "2. Wait a few seconds while the bot analyzes your data.\n"
        "3. View the generated metrics summary and high-resolution chart images.\n\n"
        "**Available Commands:**\n"
        "• `/preview [N]` — show first N rows as a table (default 5, max 20)\n"
        "• `/columns` — list all column names, types, and null counts\n"
        "• `/stats [col]` — per-column stats (count/mean/std/min/max, unique/top, date range)\n"
        "• `/sort <col> [asc|desc]` — sort rows by a column, e.g. `/sort salary desc`\n"
        "• `/filter <col> <op> <val>` — filter rows, e.g. `/filter age > 30`\n"
        "  Supported operators: `>`, `<`, `>=`, `<=`, `==`, `!=`, `contains`\n"
        "• `/export` — download the currently loaded dataset as a CSV file\n\n"
        "⚠️ **File Size Limit:** Files up to 20MB are supported."
    )
    if update.message:
        await update.message.reply_text(help_text, parse_mode="Markdown")


# ──────────────────────────────────────────────────────────────────────────────
# /preview [N]
# ──────────────────────────────────────────────────────────────────────────────

async def preview_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/preview [N]` — show first N rows of the loaded dataset."""
    df, filename = _get_df(update, context)
    if df is None:
        await _no_dataset_msg(update)
        return

    # Parse N argument
    n = 5
    if context.args:
        try:
            n = max(1, min(int(context.args[0]), 20))
        except ValueError:
            pass

    table = DataAnalyzer.dataframe_to_markdown(df, max_rows=n)

    # Telegram has a 4096 char limit; truncate if needed
    header = f"👁️ **Preview of `{filename}` — first {n} rows:**\n\n"
    body = f"```\n{table}\n```"
    msg = header + body

    if len(msg) > 4000:
        msg = header + f"```\n{table[:3800]}\n... (truncated)\n```"

    if update.message:
        await update.message.reply_text(msg, parse_mode="Markdown")


# ──────────────────────────────────────────────────────────────────────────────
# /columns
# ──────────────────────────────────────────────────────────────────────────────

async def columns_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/columns` — list all columns with dtype and null count."""
    df, filename = _get_df(update, context)
    if df is None:
        await _no_dataset_msg(update)
        return

    lines = [f"📋 **Columns in `{filename}`** ({len(df.columns)} total):\n"]
    for col in df.columns:
        dtype_str = str(df[col].dtype)
        null_count = int(df[col].isnull().sum())
        null_pct = null_count / len(df) * 100 if len(df) > 0 else 0.0
        lines.append(f"• `{col}` — {dtype_str} | {null_count} nulls ({null_pct:.1f}%)")

    msg = "\n".join(lines)
    if len(msg) > 4000:
        msg = "\n".join(lines[:50]) + f"\n\n*... and {len(df.columns) - 50} more columns*"

    if update.message:
        await update.message.reply_text(msg, parse_mode="Markdown")


# ──────────────────────────────────────────────────────────────────────────────
# /stats [col]
# ──────────────────────────────────────────────────────────────────────────────

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/stats [col]` — per-column count/mean/min/max breakdown."""
    df, filename = _get_df(update, context)
    if df is None:
        await _no_dataset_msg(update)
        return

    col = " ".join(context.args) if context.args else None

    try:
        body = DataAnalyzer.generate_column_stats(df, col)
    except ValueError as e:
        if update.message:
            await update.message.reply_text(f"❌ {str(e)}", parse_mode="Markdown")
        return

    header = f"📊 **Column Stats for `{filename}`"
    if col:
        header += f" — `{col}`"
    header += ":**\n\n"

    msg = header + body
    if len(msg) > 4000:
        msg = header + body[:3900] + "\n... (truncated)"

    if update.message:
        await update.message.reply_text(msg, parse_mode="Markdown")


# ──────────────────────────────────────────────────────────────────────────────
# /sort <col> [asc|desc]
# ──────────────────────────────────────────────────────────────────────────────

async def sort_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/sort <col> [asc|desc]` — reorder rows by a column and show a preview."""
    df, filename = _get_df(update, context)
    if df is None:
        await _no_dataset_msg(update)
        return

    args = context.args
    if not args:
        if update.message:
            await update.message.reply_text(
                "⚠️ Usage: `/sort <column> [asc|desc]`\n"
                "Example: `/sort age desc`\n"
                "Default order is ascending (`asc`).",
                parse_mode="Markdown",
            )
        return

    # Support multi-word column names: a trailing `asc`/`desc` is the direction
    if len(args) >= 2 and args[-1].lower() in ("asc", "desc"):
        col = " ".join(args[:-1])
        ascending = args[-1].lower() == "asc"
    else:
        col = " ".join(args)
        ascending = True

    try:
        sorted_df = DataAnalyzer.sort_dataframe(df, col, ascending)
    except ValueError as e:
        if update.message:
            await update.message.reply_text(f"❌ {str(e)}", parse_mode="Markdown")
        return

    order = "ascending" if ascending else "descending"
    table = DataAnalyzer.dataframe_to_markdown(sorted_df, max_rows=5)
    header = (
        f"↕️ **Sorted by `{col}` ({order})** — {len(df):,} rows\n\n"
        f"*First 5 rows:*\n"
    )
    body = f"```\n{table}\n```"
    msg = header + body
    if len(msg) > 4000:
        msg = header + f"```\n{table[:3600]}\n... (truncated)\n```"

    if update.message:
        await update.message.reply_text(msg, parse_mode="Markdown")


# ──────────────────────────────────────────────────────────────────────────────
# /filter <col> <op> <val>
# ──────────────────────────────────────────────────────────────────────────────

_NUMERIC_OPS = {">", "<", ">=", "<=", "==", "!="}

async def filter_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/filter <col> <op> <val>` — filter rows and show count + preview."""
    df, filename = _get_df(update, context)
    if df is None:
        await _no_dataset_msg(update)
        return

    if not context.args or len(context.args) < 3:
        if update.message:
            await update.message.reply_text(
                "⚠️ Usage: `/filter <column> <operator> <value>`\n"
                "Example: `/filter age > 30`\n"
                "Operators: `>` `<` `>=` `<=` `==` `!=` `contains`",
                parse_mode="Markdown",
            )
        return

    col = context.args[0]
    op = context.args[1]
    val_str = " ".join(context.args[2:])

    if col not in df.columns:
        if update.message:
            await update.message.reply_text(
                f"❌ Column `{col}` not found.\nUse `/columns` to see available columns.",
                parse_mode="Markdown",
            )
        return

    try:
        if op == "contains":
            mask = df[col].astype(str).str.contains(val_str, case=False, na=False)
        elif op in _NUMERIC_OPS:
            val = float(val_str)
            if op == ">":
                mask = df[col] > val
            elif op == "<":
                mask = df[col] < val
            elif op == ">=":
                mask = df[col] >= val
            elif op == "<=":
                mask = df[col] <= val
            elif op == "==":
                mask = df[col] == val
            elif op == "!=":
                mask = df[col] != val
        else:
            if update.message:
                await update.message.reply_text(
                    f"❌ Unknown operator `{op}`.\nSupported: `>` `<` `>=` `<=` `==` `!=` `contains`",
                    parse_mode="Markdown",
                )
            return

        filtered = df[mask]
        count = len(filtered)
        total = len(df)
        pct = count / total * 100 if total > 0 else 0.0

        table = DataAnalyzer.dataframe_to_markdown(filtered, max_rows=5)
        header = (
            f"🔍 **Filter:** `{col} {op} {val_str}`\n"
            f"**Result:** {count:,} / {total:,} rows ({pct:.1f}%)\n\n"
            f"*First 5 rows:*\n"
        )
        body = f"```\n{table}\n```"
        msg = header + body
        if len(msg) > 4000:
            msg = header + f"```\n{table[:3600]}\n... (truncated)\n```"

    except Exception as e:
        msg = f"❌ Filter error: {str(e)}"

    if update.message:
        await update.message.reply_text(msg, parse_mode="Markdown")


# ──────────────────────────────────────────────────────────────────────────────
# /export
# ──────────────────────────────────────────────────────────────────────────────

async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/export` — send the loaded dataset back as a CSV file."""
    df, filename = _get_df(update, context)
    if df is None:
        await _no_dataset_msg(update)
        return

    buf = io.BytesIO()
    df.to_csv(buf, index=False, encoding='utf-8')
    buf.seek(0)

    export_name = filename.rsplit(".", 1)[0] + "_export.csv"
    if update.message:
        await update.message.reply_document(
            document=buf,
            filename=export_name,
            caption=f"📤 Exported `{filename}` as CSV ({len(df):,} rows × {len(df.columns)} columns)",
            parse_mode="Markdown",
        )


# ──────────────────────────────────────────────────────────────────────────────
# Document upload handler
# ──────────────────────────────────────────────────────────────────────────────

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Document upload update handler."""
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

        # Load DataFrame; persist bytes in the session store (survives restarts)
        data = bytes(file_bytes)
        df = DataAnalyzer.load_dataframe(data, filename)
        context.user_data["df"] = df
        context.user_data["filename"] = filename
        user_id = _user_id(update)
        if user_id is not None:
            _get_store().save(user_id, filename, data)

        # Generate summary text
        summary_text = DataAnalyzer.generate_summary(df, filename)
        await update.message.reply_text(summary_text, parse_mode="Markdown")

        # AI insight summary (optional)
        ai_summary = DataAnalyzer.generate_ai_summary(df, filename, OPENAI_API_KEY)
        if ai_summary:
            await update.message.reply_text(
                f"🤖 **AI Insights:**\n\n{ai_summary}",
                parse_mode="Markdown"
            )

        # Generate and send chart images (distributions, heatmap, categories, time-series)
        charts = DataAnalyzer.generate_visualizations(df)
        for chart_buf, caption in charts:
            chart_buf.seek(0)
            await update.message.reply_photo(photo=chart_buf, caption=caption)

        # Session tip
        await update.message.reply_text(
        "✅ **Dataset loaded!** You can now use:\n"
        "`/preview [N]` • `/columns` • `/stats [col]` • `/sort <col>` • `/filter <col> <op> <val>` • `/export`",
            parse_mode="Markdown"
        )

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


# ──────────────────────────────────────────────────────────────────────────────
# Handler registry
# ──────────────────────────────────────────────────────────────────────────────

def get_bot_handlers():
    """Returns list of configured handlers for the python-telegram-bot application."""
    return [
        CommandHandler("start", start_command),
        CommandHandler("help", help_command),
        CommandHandler("preview", preview_command),
        CommandHandler("columns", columns_command),
        CommandHandler("stats", stats_command),
        CommandHandler("sort", sort_command),
        CommandHandler("filter", filter_command),
        CommandHandler("export", export_command),
        MessageHandler(filters.Document.ALL, handle_document),
    ]
