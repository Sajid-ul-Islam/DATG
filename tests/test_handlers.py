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
)


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
