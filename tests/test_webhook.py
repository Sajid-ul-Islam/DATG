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

    async def call():
        return await telegram_webhook(
            FakeRequest({"X-Telegram-Bot-Api-Secret-Token": "wrong"})
        )

    resp = asyncio.run(call())
    assert resp.status_code == 403
