#!/usr/bin/env python3
"""
Deployment checklist for the Telegram Data Analysis Bot on Vercel.

Verifies, in one shot:
  1. Required configuration (bot token, app/webhook URL)
  2. The deployed app is healthy  (GET /api/health)
  3. The Telegram webhook is registered and pointing at the app
     (GET getWebhookInfo), including delivery errors and pending updates

With --fix it can also safely re-register the webhook via the deployed app's
own /api/set_webhook endpoint when the checks find it misconfigured (same
action as visiting that URL in a browser). It prompts for confirmation unless
--yes is given. Read-only otherwise — never changes anything else.

Usage:
    python scripts/check_deployment.py --url https://<your-app>.vercel.app
    python scripts/check_deployment.py --url https://<your-app>.vercel.app --fix
    python scripts/check_deployment.py --token <TOKEN> --url https://<your-app>.vercel.app
    python scripts/check_deployment.py          # reads .env (TELEGRAM_BOT_TOKEN, WEBHOOK_URL)

If --url is omitted it is derived from WEBHOOK_URL in the environment/.env.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

CHECK = "\u2705"   # ✅
FAIL = "\u274c"    # ❌
WARN = "\u26a0\ufe0f"  # ⚠️
INFO = "\u2139\ufe0f"  # ℹ️

TELEGRAM_API = "https://api.telegram.org"


# ──────────────────────────────────────────────────────────────────────────────
# Pure helpers (unit-tested in tests/test_check_deployment.py)
# ──────────────────────────────────────────────────────────────────────────────

def load_env_file(path: str) -> dict:
    """Parse a simple KEY=VALUE .env file (quotes stripped, comments skipped)."""
    env = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def app_url_from_webhook(webhook_url: str) -> str:
    """Derive the app root from a webhook URL (e.g. .../api/webhook -> root)."""
    url = (webhook_url or "").rstrip("/")
    for suffix in ("/api/webhook", "/webhook"):
        if url.endswith(suffix):
            return url[: -len(suffix)]
    return url


def webhook_url_for(app_url: str) -> str:
    """The webhook path the deployed app serves."""
    return f"{app_url.rstrip('/')}/api/webhook"


def health_url_for(app_url: str) -> str:
    return f"{app_url.rstrip('/')}/api/health"


def classify_webhook_error(message: str):
    """
    Map a getWebhookInfo `last_error_message` to (category, human hint).

    Returns (None, None) for an empty message.
    """
    if not message:
        return None, None
    msg = message.lower()
    if "conflict" in msg:
        return "conflict", (
            "Another process is using this bot token via polling (getUpdates), "
            "e.g. a local `python main.py` still running. Stop it — Telegram "
            "delivers to only one destination per token."
        )
    if "unauthorized" in msg:
        return "unauthorized", (
            "Telegram rejected the webhook request — the bot token may be "
            "invalid, or the webhook secret no longer matches."
        )
    if "404" in msg or "not found" in msg or "bad request" in msg:
        return "bad_url", (
            "Telegram could not reach the webhook URL — the domain may be "
            "wrong or the deployment was removed. Re-register with "
            "/api/set_webhook."
        )
    return "unknown", (
        "Telegram reported a delivery error. Check the deployment logs and "
        "re-visit /api/set_webhook."
    )


def is_webhook_failure(row) -> bool:
    """A FAIL row that a webhook re-registration can plausibly repair."""
    icon, title, _ = row
    return icon == FAIL and title.startswith("Webhook")


def needs_fix(webhook_rows: list) -> bool:
    """True when any fixable webhook failure is present."""
    return any(is_webhook_failure(row) for row in webhook_rows)


def confirm(prompt_text: str) -> bool:
    """Ask for y/N confirmation on stdin."""
    return input(prompt_text).strip().lower() in ("y", "yes")


# ──────────────────────────────────────────────────────────────────────────────
# Network helpers
# ──────────────────────────────────────────────────────────────────────────────

def http_get_json(url: str, timeout: float = 15.0):
    """GET a URL and return (status_code_or_None, json_dict)."""
    req = urllib.request.Request(url, headers={"User-Agent": "datg-deployment-check/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(body) if body.strip() else {}
            except ValueError:
                # Not JSON (e.g. an HTML error page from a wrong domain)
                data = {"_body": body[:200]}
            return resp.status, data
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(body) if body.strip() else {}
        except ValueError:
            data = {}
        return e.code, data
    except (urllib.error.URLError, OSError) as e:
        return None, {"_error": str(e)}


def fix_webhook(app_url: str, timeout: float = 15.0):
    """
    Re-register the webhook via the deployed app's /api/set_webhook endpoint.

    This is the same action as visiting that URL in a browser: the server-side
    code re-registers with the current WEBHOOK_URL and TELEGRAM_WEBHOOK_SECRET
    from the deployment's env vars. Returns (ok, message).
    """
    status, data = http_get_json(f"{app_url.rstrip('/')}/api/set_webhook", timeout)
    if status is None:
        return False, f"Could not reach set_webhook endpoint: {data.get('_error', '')}"
    if status == 200 and data.get("status") == "success":
        return True, data.get("message", "Webhook re-registered successfully")
    detail = data.get("detail") or data.get("message") or str(data)
    return False, f"set_webhook failed (HTTP {status}): {detail}"


# ──────────────────────────────────────────────────────────────────────────────
# Checks
# ──────────────────────────────────────────────────────────────────────────────

def optional_env_info(env: dict) -> list:
    """Info-level rows for optional features."""
    rows = []
    for name, desc in (
        ("OPENAI_API_KEY", "AI insight summaries"),
        ("BLOB_READ_WRITE_TOKEN", "persistent sessions on Vercel"),
        ("TELEGRAM_WEBHOOK_SECRET", "webhook hardening"),
        ("DATABASE_PATH", "local SQLite path"),
    ):
        value = os.getenv(name) or env.get(name, "")
        rows.append((INFO, f"{name} ({desc})", "set" if value else "not set"))
    return rows


def check_health(app_url: str, timeout: float):
    """GET /api/health on the deployed app."""
    status, data = http_get_json(health_url_for(app_url), timeout)
    if status is None:
        return (FAIL, "Health endpoint unreachable", data.get("_error", ""))
    if status == 200 and data.get("status") == "ok":
        return (CHECK, "App is healthy", f"GET /api/health -> HTTP 200 {data}")
    if status == 200:
        return (WARN, "Health endpoint returned an unexpected body", str(data))
    return (FAIL, "Health endpoint failed", f"GET /api/health -> HTTP {status} {data}")


def check_webhook(token: str, expected_url: str, timeout: float, env: dict) -> list:
    """Query getWebhookInfo and report registration, delivery errors, pending."""
    status, data = http_get_json(f"{TELEGRAM_API}/bot{token}/getWebhookInfo", timeout)
    if status is None:
        return [(FAIL, "Telegram API unreachable", data.get("_error", ""))]
    if not data.get("ok"):
        description = data.get("description") or "Telegram rejected the request"
        if status is not None and status != 200:
            title = f"getWebhookInfo failed (HTTP {status})"
        else:
            title = "getWebhookInfo failed — bot token rejected"
        return [(FAIL, title, description)]

    result = data.get("result", {})
    checks = []

    registered_url = (result.get("url") or "").rstrip("/")
    expected = expected_url.rstrip("/")
    if not registered_url:
        checks.append(
            (FAIL, "Webhook is not registered", "Visit https://<app>/api/set_webhook after deploying.")
        )
    elif registered_url != expected:
        checks.append(
            (FAIL, "Webhook URL mismatch",
             f"registered: {registered_url} — expected: {expected}")
        )
    else:
        checks.append((CHECK, "Webhook is registered", registered_url))

    last_error = result.get("last_error_message")
    category, hint = classify_webhook_error(last_error)
    if category:
        checks.append((FAIL, f"Webhook delivery error: {last_error}", hint))
    else:
        checks.append((CHECK, "No webhook delivery errors", "last_error_message is empty"))

    try:
        pending = int(result.get("pending_update_count") or 0)
    except (TypeError, ValueError):
        pending = 0  # never crash on unexpected API data
    if pending:
        checks.append(
            (WARN, f"{pending} pending update(s) queued",
             "Queued updates usually drain once delivery errors clear.")
        )
    else:
        checks.append((CHECK, "No pending updates", "pending_update_count is 0"))

    if os.getenv("TELEGRAM_WEBHOOK_SECRET") or env.get("TELEGRAM_WEBHOOK_SECRET"):
        checks.append(
            (INFO, "TELEGRAM_WEBHOOK_SECRET is set",
             "The secret is write-only and can't be verified via the API. If it "
             "mismatches the registration, the bot self-heals on the next update.")
        )
    else:
        checks.append((INFO, "TELEGRAM_WEBHOOK_SECRET not set", "Webhook hardening is off (optional)."))

    return checks


# ──────────────────────────────────────────────────────────────────────────────
# Reporting
# ──────────────────────────────────────────────────────────────────────────────

def _print_rows(rows: list) -> None:
    for icon, title, detail in rows:
        line = f"  {icon} {title}"
        if detail:
            line += f" — {detail}"
        print(line)


def _failure_count(rows: list) -> int:
    return sum(1 for icon, _, _ in rows if icon == FAIL)


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> int:
    # Windows consoles default to cp1252, which cannot print emoji checkmarks.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Verify a DATG Vercel deployment: env vars, health, webhook.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/check_deployment.py --url https://myapp.vercel.app\n"
            "  python scripts/check_deployment.py --url https://myapp.vercel.app --fix\n"
            "    (--fix re-registers the webhook via /api/set_webhook if misconfigured)\n"
            "  python scripts/check_deployment.py\n"
            "    (reads TELEGRAM_BOT_TOKEN and WEBHOOK_URL from .env)"
        ),
    )
    parser.add_argument("--token", help="Telegram bot token (overrides env/.env)")
    parser.add_argument("--url", help="App root URL, e.g. https://myapp.vercel.app")
    parser.add_argument("--env-file", default=".env", help="Path to .env file (default: .env)")
    parser.add_argument("--timeout", type=float, default=15.0, help="HTTP timeout in seconds")
    parser.add_argument(
        "--fix", action="store_true",
        help="Re-register the webhook via /api/set_webhook if it is misconfigured",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="With --fix: skip the confirmation prompt",
    )
    args = parser.parse_args()

    env = load_env_file(args.env_file)
    token = args.token or os.getenv("TELEGRAM_BOT_TOKEN") or env.get("TELEGRAM_BOT_TOKEN", "")
    webhook_env = os.getenv("WEBHOOK_URL") or env.get("WEBHOOK_URL", "")
    app_url = (args.url or app_url_from_webhook(webhook_env)).rstrip("/")

    # 1. Configuration
    checks = []
    if token:
        checks.append((CHECK, "TELEGRAM_BOT_TOKEN is set", ""))
    else:
        checks.append((FAIL, "TELEGRAM_BOT_TOKEN is not set",
                       "Set it in Vercel env vars (or your .env for local runs)."))
    if app_url:
        checks.append((CHECK, f"App URL resolved: {app_url}", ""))
    else:
        checks.append((FAIL, "App URL could not be determined",
                       "Pass --url or set WEBHOOK_URL in env/.env."))
    checks.extend(optional_env_info(env))

    # 2. Health + webhook (only possible with both token and URL)
    health_row = None
    webhook_start = len(checks)
    if token and app_url:
        health_row = check_health(app_url, args.timeout)
        checks.append(health_row)
        webhook_start = len(checks)
        checks.extend(check_webhook(token, webhook_url_for(app_url), args.timeout, env))
    else:
        checks.append((FAIL, "Skipped health + webhook checks",
                       "Both the bot token and the app URL are required."))

    print("📋 DATG Deployment Checklist\n")
    _print_rows(checks)

    # 3. Optional self-fix of the webhook registration
    if args.fix and token and app_url:
        webhook_rows = checks[webhook_start:]
        if health_row is not None and health_row[0] == FAIL:
            print("\n  App health check failed — refusing to re-register the webhook")
            print("  on an unreachable deployment. Fix the deployment first.")
        elif needs_fix(webhook_rows):
            print("\n🔧 --fix requested — the webhook registration looks misconfigured.")
            if args.yes or confirm("Re-register the webhook via /api/set_webhook now? [y/N]: "):
                ok, message = fix_webhook(app_url, args.timeout)
                print(f"  {'✅' if ok else '❌'} {message}")
                if ok:
                    # Re-run the webhook checks against the fresh registration
                    checks[webhook_start:] = check_webhook(
                        token, webhook_url_for(app_url), args.timeout, env
                    )
                    print("\n📋 Webhook checks after fix:")
                    _print_rows(checks[webhook_start:])
            else:
                print("  Skipped — no changes made.")
        elif any(icon == FAIL for icon, _, _ in webhook_rows):
            print("\n  Webhook issues found, but none can be repaired by re-registering")
            print("  (e.g. an invalid bot token or an unreachable Telegram API).")
            print("  Fix the env vars and re-run.")
        else:
            print("\n  Webhook looks healthy — nothing to fix.")

    # 4. Final verdict
    fails = _failure_count(checks)
    warns = sum(1 for icon, _, _ in checks if icon == WARN)
    print()
    if fails:
        print(f"❌ {fails} critical issue(s) found. Fix them, then re-run this script.")
        return 1
    if warns:
        print(f"✅ No critical issues. ⚠️ {warns} warning(s) to review.")
    else:
        print("✅ All checks passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
