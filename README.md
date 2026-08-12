# Telegram Data Analysis Bot (DATG)

A fast, production-ready Telegram bot that processes uploaded CSV and Excel (`.xlsx`, `.xls`) files, generates data summary reports, renders high-resolution visualization charts, and lets you explore your dataset interactively with slash commands.

---

## 🌟 Key Features

- **CSV & Excel Parsing**: Automatic decoding and parsing of uploaded datasets.
- **Summary Metrics**: Overview of total rows, columns, data types, missing value percentages, and memory consumption.
- **Descriptive Statistics**: Automatic computation of mean, median, standard deviation, min, and max for numerical features.
- **Outlier Detection**: IQR-based outlier report per numeric column.
- **Time-Series Detection**: Automatic date-column detection and line charts.
- **AI Insight Summaries**: Optional plain-English data insights via OpenAI `gpt-4o-mini` (enabled with `OPENAI_API_KEY`).
- **Visual Analytics**:
  - 📊 Distribution Histograms for numerical columns.
  - 🔥 Correlation Heatmaps for multi-variable numerical relationships.
  - 🏷️ Frequency Bar Charts for top categorical features.
  - 📅 Time-Series Line Charts when date columns are detected.
- **Interactive Commands**: Explore the loaded dataset with `/preview`, `/columns`, `/stats`, `/sort`, `/filter`, and `/export`.
- **Multi-Format Report Download**: Export the full analysis with `/report` — dataset as CSV, an Excel workbook (data + summary sheets), a formatted PDF report, or a single report image (`/report all` sends every format).
- **Multi-Sheet Excel**: browse workbook tabs with `/sheets` and analyze any tab with `/sheet <name>`.
- **Load from URL**: analyze a CSV/Excel file from a direct link with `/load <url>`.
- **Google Sheets**: analyze a *public* Google Sheet with `/gsheet <url>` (no API key needed).
- **Persistent Sessions**: Uploaded datasets survive bot restarts — SQLite locally, [Vercel Blob](https://vercel.com/docs/storage/vercel-blob) on serverless deployments.
- **Dual Deployment**:
  - **Local / VPS Polling Mode**: Simple setup without webhooks or public domains.
  - **Vercel Serverless Webhook Mode**: Zero-maintenance, cost-effective serverless deployment.

---

## 🚀 Quick Start (Local Polling)

### 1. Prerequisites
- Python 3.9+ installed.
- A Telegram Bot Token from [@BotFather](https://t.me/BotFather).

### 2. Installation & Setup
```bash
# Clone repository
git clone https://github.com/your-username/telegram-data-analysis-bot.git
cd telegram-data-analysis-bot

# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env
```

Set your Telegram Bot Token in `.env`:
```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
```

### 3. Run the Bot
```bash
python main.py
```
Open Telegram, search for your bot, and send `/start` or upload a CSV file!

Optional `.env` settings:
```env
# Enable AI insight summaries (leave blank to skip)
OPENAI_API_KEY=sk-...

# SQLite database location for session persistence (local/polling mode)
DATABASE_PATH=bot_sessions.db

# Vercel Blob read/write token (persistent sessions on Vercel — optional)
BLOB_READ_WRITE_TOKEN=vercel_blob_rw_...
```

---

## 📟 Commands

After uploading a dataset, the bot remembers it (see [Session Persistence](#session-persistence)) and you can run:

| Command | Description |
|---|---|
| `/start` | Welcome message and usage overview |
| `/help` | Show command help |
| `/preview [N]` | Show the first N rows as a table (default 5, max 20) |
| `/columns` | List all columns with data types and null counts |
| `/stats [col]` | Per-column breakdown: count/mean/std/min/max (numeric), unique/top (categorical), range (dates) |
| `/sort <col> [asc|desc]` | Sort rows by a column (default ascending) |
| `/filter <col> <op> <val>` | Filter rows, e.g. `/filter age > 30` |
| `/sheets` | List the sheet tabs of the loaded Excel workbook |
| `/sheet <name>` | Analyze a specific tab, e.g. `/sheet March` |
| `/load <url>` | Download and analyze a CSV/Excel file from a link |
| `/gsheet <url>` | Analyze a public Google Sheet (share it as *Anyone with the link*) |
| `/export` | Download the loaded dataset as a CSV file |
| `/report [fmt]` | Download the analysis report as CSV, Excel, PDF, or an image (`/report all` = every format) |

Examples:
```
/stats salary
/sort age desc
/filter department == IT
```

`/filter` supports `>`, `<`, `>=`, `<=`, `==`, `!=`, and `contains`. Column names containing spaces work too (e.g. `/sort full name`).

---

## 💾 Session Persistence

Uploaded datasets are saved so they survive bot restarts:

- **Local / polling mode** — stored in a SQLite database (`bot_sessions.db` by default). Override the location with `DATABASE_PATH` in `.env`.
- **Vercel (serverless)** — stored in a [Vercel Blob](https://vercel.com/docs/storage/vercel-blob) store when `BLOB_READ_WRITE_TOKEN` is set. Create a Blob store in your Vercel dashboard and add its token to your project's Environment Variables. The serverless filesystem is read-only and ephemeral, so without this the bot falls back to in-memory sessions (datasets are lost when instances recycle).

> **Note**: Blob URLs are publicly readable by anyone who knows them (the SDK currently only supports public access). URLs are unguessable, but avoid uploading highly sensitive datasets if that matters to you.
>
> **Multi-sheet caveat**: the *selected tab* (`/sheet <name>`) is kept in memory only — after a cold start the bot reloads the workbook's first sheet. The workbook bytes themselves do persist.

---

## ⚡ Deployment Options

### Option A: Vercel Serverless Webhook (Recommended)

1. Push your repository to GitHub.
2. Import the repository into [Vercel](https://vercel.com).
3. In your Vercel Project Settings, add the Environment Variables:
   - `TELEGRAM_BOT_TOKEN`: Your Telegram Bot Token.
   - `WEBHOOK_URL`: `https://<your-vercel-app-domain>/api/webhook`
   - `OPENAI_API_KEY` *(optional)*: enables AI insight summaries.
   - `BLOB_READ_WRITE_TOKEN` *(optional)*: from a Vercel Blob store you create — enables persistent sessions across cold starts.
   - `TELEGRAM_WEBHOOK_SECRET` *(optional)*: a random string you pick — Telegram will send it with every update and the bot rejects requests without it.
4. Deploy the project.
5. Register the webhook with Telegram by visiting:
   `https://<your-vercel-app-domain>/api/set_webhook` in your browser.

> **Hardening notes:** the included `vercel.json` raises the function `maxDuration` to 300s (the Hobby maximum) so heavy analysis always completes, and `drop_pending_updates` is enabled when registering the webhook to clear stale queued updates. If you set `TELEGRAM_WEBHOOK_SECRET`, re-visit `/api/set_webhook` after changing it — but the bot now *self-heals*: if it detects a secret mismatch it automatically re-registers the webhook (rate-limited), so a forgotten re-visit can't lock the bot out. The `/api/health` endpoint is *commit-aware*: it reports the deployed git SHA (from Vercel's `VERCEL_GIT_COMMIT_SHA` env var), which the [CI deployment check](#ci-github-actions) uses to wait for the new build before verifying the deployment — so checks never run against a stale build.

---

### Option B: Railway / Render / VPS (Polling or Webhook)

Deploy as a background Python worker running `python main.py` with `TELEGRAM_BOT_TOKEN` specified as an environment variable.

---

## 🔍 Deployment Checklist

After deploying to Vercel, verify everything in one shot from your machine:

```bash
# App URL is enough (token + URL also read from .env if present)
python scripts/check_deployment.py --url https://<your-app>.vercel.app

# Or rely on .env entirely
python scripts/check_deployment.py
```

The script is read-only and checks:
- Required env vars (`TELEGRAM_BOT_TOKEN`, app URL)
- Deployed app health (`GET /api/health`)
- Webhook registration (`getWebhookInfo`): URL matches, no `last_error_message`, pending updates

It prints a ✅/❌/⚠️ checklist, explains any delivery errors (e.g. *Conflict* = local polling still running), and exits non-zero on critical issues.

Add `--fix` to safely re-register the webhook when it's misconfigured (prompts for confirmation; `--yes` skips it). The fix calls the deployed app's own `/api/set_webhook` endpoint — the same action as visiting it in a browser — then re-runs the webhook checks:

```bash
python scripts/check_deployment.py --url https://<your-app>.vercel.app --fix
```

Because Vercel builds asynchronously, the live deployment can briefly serve the *previous* commit. To wait until the app reports a specific commit before checking (its `/api/health` exposes the deployed git SHA), pass `--expect-commit` with a `--wait` budget in seconds:

```bash
python scripts/check_deployment.py --url https://<your-app>.vercel.app --expect-commit <git-sha> --wait 600
```

---

## 🤖 CI (GitHub Actions)

A workflow (`.github/workflows/deploy-check.yml`) runs on every push to `main`:

1. **Tests** — installs dependencies and runs the full pytest suite.
2. **Deployment check** — runs the [checklist](#-deployment-checklist) with `--expect-commit $GITHUB_SHA --wait 600 --fix --yes`. It first **waits (up to 10 minutes)** until Vercel finishes building and the live app reports the exact commit being pushed (via `/api/health`), so it can never validate the previous deployment; a misconfigured webhook is then repaired automatically (no manual `/api/set_webhook` visit).

To enable the deployment check, configure two settings in your GitHub repo:

- **Repository variable** `APP_URL` — e.g. `https://myapp.vercel.app`
- **Secret** `TELEGRAM_BOT_TOKEN` — your bot token

The check step is skipped until both are set. Use the **Run workflow** button in the Actions tab to run it manually anytime.

> **Note:** the wait assumes Vercel exposes the deployed commit via the `VERCEL_GIT_COMMIT_SHA` system env var (true for Git-connected deployments). If the wait times out, the workflow fails with a clear message — re-run it after Vercel finishes building.

---

## 🧪 Running Automated Tests

Run unit tests to verify dataset loading, statistics, sorting, filtering, chart generation, report export (Excel/PDF/image), session persistence, webhook hardening, and error handling:

```bash
pytest
```

---

## 📂 Project Structure

```
DATG/
├── .github/
│   └── workflows/
│       └── deploy-check.yml   # CI: tests + deployment check (waits for the new build)
├── api/
│   ├── __init__.py
│   └── index.py               # FastAPI serverless webhook endpoint (Vercel)
├── bot/
│   ├── __init__.py
│   ├── analyzer.py            # Pandas analysis & Matplotlib visualization engine
│   ├── config.py              # Environment configuration loader
│   ├── handlers.py            # Telegram update handlers (commands + document listener)
│   ├── session_store.py       # SQLite-backed session persistence
│   └── cloud_store.py         # Vercel Blob-backed session persistence (serverless)
├── tests/
│   ├── __init__.py
│   ├── test_analyzer.py       # Analyzer unit tests (summary, stats, sort, charts, reports)
│   ├── test_check_deployment.py  # Deployment checklist helper tests
│   ├── test_handlers.py       # URL / Google Sheets / report-export helper tests
│   ├── test_session_store.py  # SQLite session persistence tests
│   ├── test_cloud_store.py    # Vercel Blob session persistence tests (offline)
│   └── test_webhook.py        # Webhook secret-header tests
├── .env.example
├── main.py                    # Local polling entry point
├── scripts/
│   └── check_deployment.py    # Deployment verification (env/health/webhook, --fix, --expect-commit)
├── README.md
├── requirements.txt           # Python dependencies
└── vercel.json                # Vercel serverless routing config
```

---

## 📜 License
MIT License. Free to use and modify!
