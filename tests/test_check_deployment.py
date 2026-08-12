"""
Unit tests for the pure helpers in scripts/check_deployment.py.

Network calls are intentionally not exercised here.
"""
import scripts.check_deployment as mod

from scripts.check_deployment import (
    CHECK,
    FAIL,
    app_url_from_webhook,
    classify_webhook_error,
    confirm,
    fix_webhook,
    health_url_for,
    is_webhook_failure,
    load_env_file,
    needs_fix,
    webhook_url_for,
)


def test_load_env_file_parses_and_skips_comments(tmp_path):
    p = tmp_path / ".env"
    p.write_text(
        "# comment line\n"
        "TELEGRAM_BOT_TOKEN=123:abc\n"
        'WEBHOOK_URL="https://a.com/api/webhook"\n'
        "\n"
        "OPENAI_API_KEY='sk-x'\n"
        "EMPTY=\n"
    )
    env = load_env_file(str(p))
    assert env["TELEGRAM_BOT_TOKEN"] == "123:abc"
    assert env["WEBHOOK_URL"] == "https://a.com/api/webhook"
    assert env["OPENAI_API_KEY"] == "sk-x"
    assert env["EMPTY"] == ""


def test_load_env_file_missing_file_returns_empty(tmp_path):
    assert load_env_file(str(tmp_path / "nope.env")) == {}


def test_app_url_from_webhook():
    assert app_url_from_webhook("https://myapp.vercel.app/api/webhook") == "https://myapp.vercel.app"
    assert app_url_from_webhook("https://myapp.vercel.app/webhook") == "https://myapp.vercel.app"
    assert app_url_from_webhook("https://myapp.vercel.app/") == "https://myapp.vercel.app"
    assert app_url_from_webhook("https://myapp.vercel.app") == "https://myapp.vercel.app"


def test_url_helpers():
    assert webhook_url_for("https://myapp.vercel.app/") == "https://myapp.vercel.app/api/webhook"
    assert health_url_for("https://myapp.vercel.app") == "https://myapp.vercel.app/api/health"


def test_classify_webhook_error_empty():
    assert classify_webhook_error("") == (None, None)
    assert classify_webhook_error(None) == (None, None)


def test_classify_webhook_error_conflict():
    category, hint = classify_webhook_error("Conflict: terminated by other getUpdates request")
    assert category == "conflict"
    assert "polling" in hint


def test_classify_webhook_error_unauthorized():
    category, _ = classify_webhook_error("Unauthorized")
    assert category == "unauthorized"


def test_classify_webhook_error_bad_url():
    category, _ = classify_webhook_error("404 Not Found")
    assert category == "bad_url"
    category, _ = classify_webhook_error("Bad Request: wrong URL")
    assert category == "bad_url"


def test_classify_webhook_error_unknown():
    category, _ = classify_webhook_error("Some weird delivery error")
    assert category == "unknown"


# ──────────────────────────────────────────────────────────────────────────────
# --fix logic
# ──────────────────────────────────────────────────────────────────────────────


def test_is_webhook_failure_only_webhook_rows():
    assert is_webhook_failure((FAIL, "Webhook URL mismatch", "a vs b")) is True
    assert is_webhook_failure((FAIL, "Webhook is not registered", "")) is True
    assert is_webhook_failure((FAIL, "Webhook delivery error: Conflict", "hint")) is True
    # Token/API problems are NOT fixable by re-registering the webhook
    assert is_webhook_failure((FAIL, "getWebhookInfo failed (HTTP 401)", "Unauthorized")) is False
    assert is_webhook_failure((CHECK, "Webhook is registered", "url")) is False
    assert is_webhook_failure((FAIL, "Health endpoint failed", "HTTP 500")) is False


def test_needs_fix_detects_fixable_failures():
    rows = [
        (CHECK, "TELEGRAM_BOT_TOKEN is set", ""),
        (FAIL, "Webhook URL mismatch", "registered: a — expected: b"),
        (FAIL, "getWebhookInfo failed (HTTP 401)", "Unauthorized"),
    ]
    assert needs_fix(rows) is True


def test_needs_fix_false_when_only_unfixable():
    rows = [(FAIL, "getWebhookInfo failed (HTTP 401)", "Unauthorized")]
    assert needs_fix(rows) is False


def test_needs_fix_false_when_healthy():
    rows = [(CHECK, "Webhook is registered", "url"), (CHECK, "No webhook delivery errors", "")]
    assert needs_fix(rows) is False


def test_fix_webhook_success(monkeypatch):
    monkeypatch.setattr(
        mod, "http_get_json",
        lambda url, timeout=15: (
            200,
            {"status": "success", "message": "Webhook set successfully to X (secret token enabled)"},
        ),
    )
    ok, message = fix_webhook("https://app.example")
    assert ok is True
    assert "successfully" in message


def test_fix_webhook_hits_the_set_webhook_endpoint(monkeypatch):
    seen = {}

    def fake_get(url, timeout=15):
        seen["url"] = url
        return (200, {"status": "success", "message": "ok"})

    monkeypatch.setattr(mod, "http_get_json", fake_get)
    fix_webhook("https://app.example/")
    assert seen["url"] == "https://app.example/api/set_webhook"


def test_fix_webhook_reports_endpoint_failure(monkeypatch):
    monkeypatch.setattr(
        mod, "http_get_json",
        lambda url, timeout=15: (400, {"detail": "TELEGRAM_BOT_TOKEN and WEBHOOK_URL must be configured."}),
    )
    ok, message = fix_webhook("https://app.example")
    assert ok is False
    assert "HTTP 400" in message


def test_fix_webhook_unreachable(monkeypatch):
    monkeypatch.setattr(
        mod, "http_get_json",
        lambda url, timeout=15: (None, {"_error": "timed out"}),
    )
    ok, message = fix_webhook("https://app.example")
    assert ok is False
    assert "timed out" in message


def test_confirm_accepts_yes(monkeypatch):
    for answer in ("y", "Y", "yes", "YES"):
        monkeypatch.setattr("builtins.input", lambda prompt, a=answer: a)
        assert confirm("Proceed? ") is True


def test_confirm_rejects_other(monkeypatch):
    for answer in ("n", "", "maybe"):
        monkeypatch.setattr("builtins.input", lambda prompt, a=answer: a)
        assert confirm("Proceed? ") is False
