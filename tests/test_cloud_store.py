"""
Offline unit tests for the Vercel Blob session store.

The vercel_blob SDK and HTTP calls are faked so tests never hit the network.
"""
import io
import json
import sys

import pandas as pd
import pytest

from bot.analyzer import DataAnalyzer
from bot.cloud_store import BlobSessionStore


class FakeBlob:
    def __init__(self, pathname, content):
        self.pathname = pathname
        self.content = content
        self.url = f"https://store.public.blob.vercel-storage.com/{pathname}"


class FakeBlobModule:
    """In-memory stand-in for the vercel_blob SDK."""

    def __init__(self):
        self.blobs = {}
        self.puts = []  # (path, data, options) recorded for assertions

    def put(self, path, data, options=None, timeout=10, **kwargs):
        self.puts.append((path, bytes(data), dict(options or {})))
        self.blobs[path] = FakeBlob(path, bytes(data))
        return {"url": self.blobs[path].url, "pathname": path}

    def list(self, options=None):
        prefix = (options or {}).get("prefix", "")
        matched = [b for p, b in sorted(self.blobs.items()) if p.startswith(prefix)]
        return {
            "blobs": [{"pathname": b.pathname, "url": b.url} for b in matched],
            "hasMore": False,
        }

    def delete(self, urls):
        for url in urls or []:
            for path in list(self.blobs):
                if self.blobs[path].url == url:
                    del self.blobs[path]


class FakeResponse:
    """Fake requests.Response that serves bytes from the in-memory store."""

    def __init__(self, sdk, url):
        self._sdk = sdk
        self._url = url

    def raise_for_status(self):
        pass

    @property
    def content(self):
        for b in self._sdk.blobs.values():
            if b.url == self._url:
                return b.content
        raise RuntimeError(f"Blob not found for URL {self._url}")


@pytest.fixture
def blob_env(monkeypatch):
    """Install the fake SDK and fake HTTP layer, then return the fake SDK."""
    fake = FakeBlobModule()
    monkeypatch.setitem(sys.modules, "vercel_blob", fake)

    import requests
    monkeypatch.setattr(requests, "get", lambda url, timeout=10: FakeResponse(fake, url))
    return fake


def test_load_unknown_user_returns_none(blob_env):
    store = BlobSessionStore()
    assert store.load(999) is None


def test_save_and_load_roundtrip(blob_env):
    store = BlobSessionStore()
    store.save(123, "data.csv", b"a,b\n1,2\n")

    filename, data = store.load(123)
    assert filename == "data.csv"
    assert data == b"a,b\n1,2\n"


def test_save_overwrites_existing_session(blob_env):
    store = BlobSessionStore()
    store.save(1, "a.csv", b"x")
    store.save(1, "b.csv", b"y")

    assert store.load(1) == ("b.csv", b"y")
    data_blobs = [p for p in blob_env.blobs if p.endswith("/data")]
    assert len(data_blobs) == 1

    # Every put must request overwrite and skip the CDN cache, otherwise a
    # re-uploaded dataset could be shadowed by a stale cached copy.
    for _, _, options in blob_env.puts:
        assert options.get("allowOverwrite") == "true"
        assert options.get("cacheControlMaxAge") == "0"


def test_clear_removes_session(blob_env):
    store = BlobSessionStore()
    store.save(1, "a.csv", b"x")
    store.clear(1)
    assert store.load(1) is None
    assert blob_env.blobs == {}


def test_clear_only_removes_that_user(blob_env):
    store = BlobSessionStore()
    store.save(1, "a.csv", b"x")
    store.save(2, "b.csv", b"y")
    store.clear(1)
    assert store.load(1) is None
    assert store.load(2) == ("b.csv", b"y")


def test_user_ids_do_not_collide(blob_env):
    store = BlobSessionStore()
    store.save(123, "a.csv", b"x")
    store.save(1234, "b.csv", b"y")

    assert store.load(123) == ("a.csv", b"x")
    assert store.load(1234) == ("b.csv", b"y")


def test_restored_bytes_reparse_to_dataframe(blob_env):
    buf = io.BytesIO()
    pd.DataFrame({"x": [1, 2, 3]}).to_csv(buf, index=False)

    store = BlobSessionStore()
    store.save(7, "test.csv", buf.getvalue())

    filename, data = store.load(7)
    df = DataAnalyzer.load_dataframe(data, filename)
    assert list(df.columns) == ["x"]
    assert len(df) == 3


def test_missing_meta_uses_default_filename(blob_env):
    store = BlobSessionStore()
    store.save(5, "weird.csv", b"a\n1\n")
    # Simulate a lost/older metadata blob
    for path in list(blob_env.blobs):
        if path.endswith("meta.json"):
            del blob_env.blobs[path]

    filename, data = store.load(5)
    assert filename == "uploaded_file.csv"
    assert data == b"a\n1\n"


def test_meta_blob_contains_filename(blob_env):
    store = BlobSessionStore()
    store.save(42, "sales report 2024.csv", b"a\n1\n")

    meta = json.loads(blob_env.blobs["sessions/42/meta.json"].content.decode("utf-8"))
    assert meta == {"filename": "sales report 2024.csv"}


def test_load_returns_none_when_fetch_fails(blob_env, monkeypatch):
    import requests

    store = BlobSessionStore()
    store.save(1, "a.csv", b"x")

    def boom(url, timeout=10):
        raise requests.HTTPError("fetch failed")

    monkeypatch.setattr(requests, "get", boom)
    assert store.load(1) is None


def test_available_false_without_sdk(monkeypatch):
    monkeypatch.setitem(sys.modules, "vercel_blob", None)
    store = BlobSessionStore()
    assert store.available is False


def test_unavailable_store_degrades_gracefully(monkeypatch):
    """Without the SDK, save/load/clear become no-ops (must not raise)."""
    monkeypatch.setitem(sys.modules, "vercel_blob", None)
    store = BlobSessionStore()
    store.save(1, "a.csv", b"x")
    assert store.load(1) is None
    store.clear(1)
