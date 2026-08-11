# Telegram Data Analysis Bot (DATG)

A fast, production-ready Telegram bot that processes uploaded CSV and Excel (`.xlsx`, `.xls`) files, generates data summary reports, and renders high-resolution visualization charts (histograms, correlation heatmaps, categorical distribution charts).

---

## 🌟 Key Features

- **CSV & Excel Parsing**: Automatic decoding and parsing of uploaded datasets.
- **Summary Metrics**: Overview of total rows, columns, data types, missing value percentages, and memory consumption.
- **Descriptive Statistics**: Automatic computation of mean, median, standard deviation, min, and max for numerical features.
- **Visual Analytics**:
  - 📊 Distribution Histograms for numerical columns.
  - 🔥 Correlation Heatmaps for multi-variable numerical relationships.
  - 🏷️ Frequency Bar Charts for top categorical features.
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

---

## ⚡ Deployment Options

### Option A: Vercel Serverless Webhook (Recommended)

1. Push your repository to GitHub.
2. Import the repository into [Vercel](https://vercel.com).
3. In your Vercel Project Settings, add the Environment Variable:
   - `TELEGRAM_BOT_TOKEN`: Your Telegram Bot Token.
   - `WEBHOOK_URL`: `https://<your-vercel-app-domain>/api/webhook`
4. Deploy the project.
5. Register the webhook with Telegram by visiting:
   `https://<your-vercel-app-domain>/api/set_webhook` in your browser.

---

### Option B: Railway / Render / VPS (Polling or Webhook)

Deploy as a background Python worker running `python main.py` with `TELEGRAM_BOT_TOKEN` specified as an environment variable.

---

## 🧪 Running Automated Tests

Run unit tests to verify dataset loading, statistics formatting, chart generation, and error handling:

```bash
pytest
```

---

## 📂 Project Structure

```
DATG/
├── api/
│   ├── __init__.py
│   └── index.py            # FastAPI serverless webhook endpoint (Vercel)
├── bot/
│   ├── __init__.py
│   ├── analyzer.py         # Pandas analysis & Matplotlib visualization engine
│   ├── config.py           # Environment configuration loader
│   └── handlers.py         # Telegram update handlers (/start, /help, document listener)
├── tests/
│   ├── __init__.py
│   └── test_analyzer.py    # Pytest automated test suite
├── .env.example
├── main.py                 # Local polling entry point
├── README.md
├── requirements.txt        # Python dependencies
└── vercel.json             # Vercel serverless routing config
```

---

## 📜 License
MIT License. Free to use and modify!
