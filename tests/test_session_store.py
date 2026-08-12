import io
import pandas as pd
import pytest
from bot.analyzer import DataAnalyzer
from bot.session_store import SessionStore


def test_load_unknown_user_returns_none(tmp_path):
    store = SessionStore(str(tmp_path / "sessions.db"))
    assert store.load(123) is None


def test_save_and_load_roundtrip(tmp_path):
    store = SessionStore(str(tmp_path / "sessions.db"))
    store.save(123, "data.csv", b"a,b\n1,2\n")

    filename, data = store.load(123)
    assert filename == "data.csv"
    assert data == b"a,b\n1,2\n"


def test_save_overwrites_existing_session(tmp_path):
    store = SessionStore(str(tmp_path / "sessions.db"))
    store.save(1, "a.csv", b"x")
    store.save(1, "b.csv", b"y")

    assert store.load(1) == ("b.csv", b"y")


def test_clear_removes_session(tmp_path):
    store = SessionStore(str(tmp_path / "sessions.db"))
    store.save(1, "a.csv", b"x")
    store.clear(1)
    assert store.load(1) is None


def test_session_survives_restart(tmp_path):
    """A new store instance on the same DB file simulates a bot restart."""
    db_path = str(tmp_path / "sessions.db")
    SessionStore(db_path).save(42, "data.csv", b"a,b\n1,2\n")

    restarted = SessionStore(db_path)
    assert restarted.load(42) == ("data.csv", b"a,b\n1,2\n")


def test_restored_bytes_reparse_to_dataframe(tmp_path):
    buf = io.BytesIO()
    pd.DataFrame({"x": [1, 2, 3]}).to_csv(buf, index=False)
    payload = buf.getvalue()

    store = SessionStore(str(tmp_path / "sessions.db"))
    store.save(7, "test.csv", payload)

    filename, data = store.load(7)
    df = DataAnalyzer.load_dataframe(data, filename)
    assert list(df.columns) == ["x"]
    assert len(df) == 3


def test_memory_db(tmp_path):
    store = SessionStore(":memory:")
    store.save(1, "a.csv", b"x")
    assert store.load(1) == ("a.csv", b"x")
    store.close()


def test_unavailable_store_degrades_gracefully():
    """Simulates a read-only filesystem (e.g. Vercel): save/load become no-ops."""
    store = SessionStore("no_such_dir/sessions.db")
    assert store.available is False
    store.save(1, "a.csv", b"x")  # must not raise
    assert store.load(1) is None   # must not raise
    store.clear(1)                 # must not raise


def test_close_releases_connection(tmp_path):
    db_path = str(tmp_path / "sessions.db")
    store = SessionStore(db_path)
    store.save(1, "a.csv", b"x")
    store.close()
    assert store.available is False
    # A new store on the same file still works after close
    assert SessionStore(db_path).load(1) == ("a.csv", b"x")
