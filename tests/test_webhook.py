"""
Unit tests for the Vercel webhook endpoint hardening (api/index.py).

Only the pure secret-token check is tested — no network or Telegram calls.
"""
import pytest

from api.index import _check_secret_header


class FakeHeaders:
    """Mimics Starlette's case-insensitive Headers.get()."""

    def __init__(self, headers=None):
        self._headers = {k.lower(): v for k, v in (headers or {}).items()}

    def get(self, key, default=None):
        return self._headers.get(key.lower(), default)


class FakeRequest:
    def __init__(self, headers=None):
        self.headers = FakeHeaders(headers)


def test_no_secret_configured_allows_all(monkeypatch):
    monkeypatch.setattr("api.index.TELEGRAM_WEBHOOK_SECRET", "")
    assert _check_secret_header(FakeRequest({"X-Telegram-Bot-Api-Secret-Token": "x"})) is True
    assert _check_secret_header(FakeRequest({})) is True


def test_matching_secret_allows(monkeypatch):
    monkeypatch.setattr("api.index.TELEGRAM_WEBHOOK_SECRET", "s3cret")
    req = FakeRequest({"X-Telegram-Bot-Api-Secret-Token": "s3cret"})
    assert _check_secret_header(req) is True


def test_mismatched_secret_rejects(monkeypatch):
    monkeypatch.setattr("api.index.TELEGRAM_WEBHOOK_SECRET", "s3cret")
    req = FakeRequest({"X-Telegram-Bot-Api-Secret-Token": "wrong"})
    assert _check_secret_header(req) is False


def test_missing_secret_header_rejects_when_configured(monkeypatch):
    monkeypatch.setattr("api.index.TELEGRAM_WEBHOOK_SECRET", "s3cret")
    assert _check_secret_header(FakeRequest({})) is False


def test_webhook_endpoint_rejects_bad_secret(monkeypatch):
    """The endpoint itself returns 403 before touching the update body."""
    import asyncio

    from api.index import telegram_webhook

    monkeypatch.setattr("api.index.TELEGRAM_WEBHOOK_SECRET", "s3cret")

    async def fake_self_heal():
        pass

    monkeypatch.setattr("api.index._self_heal_webhook", fake_self_heal)

    async def call():
        return await telegram_webhook(
            FakeRequest({"X-Telegram-Bot-Api-Secret-Token": "wrong"})
        )

    resp = asyncio.run(call())
    assert resp.status_code == 403


def test_webhook_endpoint_self_heals_on_bad_secret(monkeypatch):
    """A mismatched secret triggers the self-heal AND still rejects the update."""
    import asyncio

    from api.index import telegram_webhook

    monkeypatch.setattr("api.index.TELEGRAM_WEBHOOK_SECRET", "s3cret")
    healed = []

    async def fake_self_heal():
        healed.append(True)

    monkeypatch.setattr("api.index._self_heal_webhook", fake_self_heal)

    async def call():
        return await telegram_webhook(
            FakeRequest({"X-Telegram-Bot-Api-Secret-Token": "wrong"})
        )

    resp = asyncio.run(call())
    assert resp.status_code == 403
    assert healed == [True]


def test_self_heal_registers_secret_and_is_rate_limited(monkeypatch):
    """Self-heal re-registers with the secret and only fires once per window."""
    import asyncio

    import api.index

    calls = []

    class FakeBot:
        async def set_webhook(self, url, secret_token=None, drop_pending_updates=False):
            calls.append((url, secret_token, drop_pending_updates))

    class FakeApp:
        bot = FakeBot()

    async def fake_get_app():
        return FakeApp()

    monkeypatch.setattr(api.index, "get_telegram_app", fake_get_app)
    monkeypatch.setattr(api.index, "WEBHOOK_URL", "https://app.example/api/webhook")
    monkeypatch.setattr(api.index, "TELEGRAM_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setattr(api.index, "_last_self_heal_attempt", 0.0)

    async def run_twice():
        await api.index._self_heal_webhook()
        await api.index._self_heal_webhook()

    asyncio.run(run_twice())
    assert calls == [("https://app.example/api/webhook", "s3cret", False)]


def test_self_heal_never_drops_pending_updates(monkeypatch):
    """Self-heal must not clear queued updates while repairing registration."""
    import asyncio

    import api.index

    calls = []

    class FakeBot:
        async def set_webhook(self, url, secret_token=None, drop_pending_updates=False):
            calls.append(drop_pending_updates)

    class FakeApp:
        bot = FakeBot()

    async def fake_get_app():
        return FakeApp()

    monkeypatch.setattr(api.index, "get_telegram_app", fake_get_app)
    monkeypatch.setattr(api.index, "WEBHOOK_URL", "https://app.example/api/webhook")
    monkeypatch.setattr(api.index, "TELEGRAM_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setattr(api.index, "_last_self_heal_attempt", 0.0)

    asyncio.run(api.index._self_heal_webhook())
    assert calls == [False]


def test_self_heal_handles_missing_token_gracefully(monkeypatch):
    """If the app can't be built (no token), the heal logs and does not raise."""
    import asyncio

    import api.index

    async def boom():
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not configured.")

    monkeypatch.setattr(api.index, "get_telegram_app", boom)
    monkeypatch.setattr(api.index, "_last_self_heal_attempt", 0.0)

    # Must not raise — the exception is caught and logged inside the heal.
    asyncio.run(api.index._self_heal_webhook())
