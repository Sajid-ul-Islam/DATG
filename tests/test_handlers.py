"""
Unit tests for the URL / Google Sheets helpers in bot/handlers.py.

Network calls are faked — nothing is downloaded during tests.
"""
import pytest
import requests

from bot.handlers import (
    _derive_filename_from_url,
    _download_bytes,
    _gsheet_export_url,
    _is_blocked_host,
    _parse_gsheet_url,
    _report_doc,
)


# ──────────────────────────────────────────────────────────────────────────────
# /report — _report_doc
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def report_df():
    import pandas as pd
    return pd.DataFrame({"Age": [25, 30, 35], "Dept": ["HR", "IT", "IT"]})


def test_report_doc_csv(report_df):
    buf, name, caption = _report_doc(report_df, "sales.csv", "csv")
    assert name == "sales_export.csv"
    assert "CSV" in caption
    assert buf.getvalue().startswith(b"Age,Dept")


def test_report_doc_excel(report_df):
    buf, name, caption = _report_doc(report_df, "sales.csv", "xlsx")
    assert name == "sales_report.xlsx"
    assert buf.getvalue()[:2] == b"PK"


def test_report_doc_pdf(report_df):
    buf, name, caption = _report_doc(report_df, "sales.csv", "pdf")
    assert name == "sales_report.pdf"
    assert buf.getvalue().startswith(b"%PDF")


def test_report_doc_png(report_df):
    buf, name, caption = _report_doc(report_df, "sales.csv", "png")
    assert name == "sales_report.png"
    assert buf.getvalue().startswith(b"\x89PNG\r\n\x1a\n")


def test_report_doc_unknown_format_raises(report_df):
    with pytest.raises(ValueError, match="Unknown report format"):
        _report_doc(report_df, "sales.csv", "docx")


# ──────────────────────────────────────────────────────────────────────────────
# Host blocking
# ──────────────────────────────────────────────────────────────────────────────

def test_blocked_hosts():
    assert _is_blocked_host("http://localhost/x.csv") is True
    assert _is_blocked_host("http://127.0.0.1/x.csv") is True
    assert _is_blocked_host("http://[::1]/x.csv") is True
    assert _is_blocked_host("http://192.168.1.10/x.csv") is True
    assert _is_blocked_host("http://10.0.0.5/x.csv") is True
    assert _is_blocked_host("http://172.16.5.5/x.csv") is True
    assert _is_blocked_host("http://172.31.1.1/x.csv") is True
    assert _is_blocked_host("http://169.254.169.254/x.csv") is True


def test_allowed_hosts():
    assert _is_blocked_host("https://example.com/data.csv") is False
    assert _is_blocked_host("https://docs.google.com/spreadsheets/d/abc") is False
    assert _is_blocked_host("http://172.32.0.1/x.csv") is False  # public range


# ──────────────────────────────────────────────────────────────────────────────
# Filename derivation
# ──────────────────────────────────────────────────────────────────────────────

def test_filename_from_url_path():
    assert _derive_filename_from_url("https://example.com/data.csv") == "data.csv"
    assert _derive_filename_from_url("https://example.com/folder/Book1.xlsx") == "Book1.xlsx"


def test_filename_from_content_type():
    assert _derive_filename_from_url("https://example.com/download?id=1", "text/csv") == "data.csv"
    assert _derive_filename_from_url("https://example.com/download?id=1", "application/vnd.ms-excel") == "data.xlsx"


def test_filename_default():
    assert _derive_filename_from_url("https://example.com/download?id=1", "") == "data.csv"


# ──────────────────────────────────────────────────────────────────────────────
# Google Sheets URL parsing
# ──────────────────────────────────────────────────────────────────────────────

def test_parse_gsheet_url_standard():
    sheet_id, gid = _parse_gsheet_url("https://docs.google.com/spreadsheets/d/AbC123xyz/edit")
    assert sheet_id == "AbC123xyz"
    assert gid is None


def test_parse_gsheet_url_with_gid():
    sheet_id, gid = _parse_gsheet_url("https://docs.google.com/spreadsheets/d/AbC123xyz/edit#gid=456")
    assert sheet_id == "AbC123xyz"
    assert gid == "456"


def test_parse_gsheet_url_export_form():
    sheet_id, gid = _parse_gsheet_url("https://docs.google.com/spreadsheets/d/AbC123xyz/export?format=csv")
    assert sheet_id == "AbC123xyz"
    assert gid is None


def test_parse_gsheet_url_invalid():
    assert _parse_gsheet_url("https://example.com/not-a-sheet") == (None, None)


def test_gsheet_export_url():
    assert _gsheet_export_url("AbC123xyz") == \
        "https://docs.google.com/spreadsheets/d/AbC123xyz/export?format=csv"
    assert _gsheet_export_url("AbC123xyz", "456") == \
        "https://docs.google.com/spreadsheets/d/AbC123xyz/export?format=csv&gid=456"


# ──────────────────────────────────────────────────────────────────────────────
# Download helper (mocked transport)
# ──────────────────────────────────────────────────────────────────────────────

class FakeResponse:
    def __init__(self, chunks, headers=None, status=200, is_redirect=False):
        self._chunks = chunks
        self.headers = headers or {}
        self._status = status
        self.is_redirect = is_redirect

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self._status >= 400:
            raise requests.HTTPError(f"HTTP {self._status}")

    def iter_content(self, chunk_size=64 * 1024):
        yield from self._chunks


def _patch_download(monkeypatch, response):
    import bot.handlers as handlers
    monkeypatch.setattr(handlers.requests, "get", lambda *a, **k: response)


def test_download_bytes_ok(monkeypatch):
    _patch_download(monkeypatch, FakeResponse([b"a,b\n1,2\n"], {"Content-Type": "text/csv"}))
    data, content_type = _download_bytes("https://example.com/data.csv")
    assert data == b"a,b\n1,2\n"
    assert content_type == "text/csv"


def test_download_bytes_http_error(monkeypatch):
    _patch_download(monkeypatch, FakeResponse([], status=404))
    with pytest.raises(requests.HTTPError):
        _download_bytes("https://example.com/missing.csv")


def test_download_bytes_size_cap(monkeypatch):
    _patch_download(monkeypatch, FakeResponse([b"x" * (1024 * 1024)] * 25))
    with pytest.raises(ValueError, match="20MB limit"):
        _download_bytes("https://example.com/huge.csv")


def test_download_bytes_rejects_bad_scheme(monkeypatch):
    with pytest.raises(ValueError, match="http"):
        _download_bytes("ftp://example.com/data.csv")


def test_download_bytes_rejects_private_host(monkeypatch):
    with pytest.raises(ValueError, match="private"):
        _download_bytes("http://127.0.0.1/data.csv")


def test_download_bytes_follows_redirects(monkeypatch):
    import bot.handlers as handlers

    calls = []

    def fake_get(url, stream=True, timeout=30, allow_redirects=False, headers=None):
        calls.append(url)
        if len(calls) == 1:
            return FakeResponse([], {"Location": "/real.csv"}, is_redirect=True)
        return FakeResponse([b"a,b\n1,2\n"], {"Content-Type": "text/csv"})

    monkeypatch.setattr(handlers.requests, "get", fake_get)
    data, content_type = _download_bytes("https://example.com/start")
    assert calls == ["https://example.com/start", "https://example.com/real.csv"]
    assert data == b"a,b\n1,2\n"
    assert content_type == "text/csv"


def test_download_bytes_blocks_redirect_to_private(monkeypatch):
    import bot.handlers as handlers

    def fake_get(url, stream=True, timeout=30, allow_redirects=False, headers=None):
        return FakeResponse([], {"Location": "http://127.0.0.1:8080/x"}, is_redirect=True)

    monkeypatch.setattr(handlers.requests, "get", fake_get)
    with pytest.raises(ValueError, match="private"):
        _download_bytes("https://example.com/start")


def test_download_bytes_too_many_redirects(monkeypatch):
    import bot.handlers as handlers

    def fake_get(url, stream=True, timeout=30, allow_redirects=False, headers=None):
        return FakeResponse([], {"Location": "/loop"}, is_redirect=True)

    monkeypatch.setattr(handlers.requests, "get", fake_get)
    with pytest.raises(ValueError, match="Too many redirects"):
        _download_bytes("https://example.com/start")


# ──────────────────────────────────────────────────────────────────────────────
# /clear — clear_command
# ──────────────────────────────────────────────────────────────────────────────

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def _make_update(text=""):
    """Build a minimal mock Update with a message."""
    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 42
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    return update


def _make_context(user_data=None):
    ctx = MagicMock()
    ctx.user_data = user_data or {}
    return ctx


def test_clear_command_with_dataset():
    """clear_command should wipe user_data and confirm deletion."""
    from bot.handlers import clear_command

    update = _make_update()
    ctx = _make_context({"df": "dummy_df", "filename": "data.csv", "sheet": "Sheet1"})

    with patch("bot.handlers._get_store") as mock_store:
        mock_store.return_value.clear = MagicMock()
        asyncio.run(clear_command(update, ctx))

    assert "df" not in ctx.user_data
    assert "filename" not in ctx.user_data
    assert "sheet" not in ctx.user_data
    mock_store.return_value.clear.assert_called_once_with(42)
    update.message.reply_text.assert_called_once()
    call_text = update.message.reply_text.call_args[0][0]
    assert "cleared" in call_text.lower()


def test_clear_command_no_dataset():
    """clear_command with no loaded dataset should give an informational message."""
    from bot.handlers import clear_command

    update = _make_update()
    ctx = _make_context({})

    with patch("bot.handlers._get_store") as mock_store:
        mock_store.return_value.clear = MagicMock()
        asyncio.run(clear_command(update, ctx))

    call_text = update.message.reply_text.call_args[0][0]
    assert "nothing to clear" in call_text.lower() or "no dataset" in call_text.lower()


# ──────────────────────────────────────────────────────────────────────────────
# filter _NUMERIC_OPS — non-numeric value guard
# ──────────────────────────────────────────────────────────────────────────────

def test_filter_rejects_non_numeric_for_numeric_op():
    """filter_command should reply with an error (not crash) when val is not a number."""
    from bot.handlers import filter_command
    import pandas as pd

    df = pd.DataFrame({"age": [25, 30, 35]})
    update = _make_update()
    ctx = _make_context({"df": df, "filename": "data.csv"})
    ctx.args = ["age", ">", "not_a_number"]

    asyncio.run(filter_command(update, ctx))

    update.message.reply_text.assert_called_once()
    call_text = update.message.reply_text.call_args[0][0]
    assert "not_a_number" in call_text or "valid number" in call_text.lower()


