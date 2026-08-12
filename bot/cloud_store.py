"""
Vercel Blob-backed session persistence.

Stores the raw uploaded file bytes (plus filename) per Telegram user in a
Vercel Blob store so datasets survive cold starts and instance recycling on
serverless deployments (e.g. Vercel). Implements the same interface as the
SQLite ``SessionStore`` (save/load/clear/available) and degrades gracefully to
no-op behavior if the SDK or token is unavailable.

Layout per user (prefix "sessions"):
    sessions/{user_id}/data       -> raw file bytes
    sessions/{user_id}/meta.json  -> {"filename": "..."}
"""
import json
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_PREFIX = "sessions"
_FETCH_TIMEOUT = 60    # downloading a stored dataset
_UPLOAD_TIMEOUT = 120  # uploading up to 20 MB of file bytes


class BlobSessionStore:
    """Persists (filename, file bytes) per user id in a Vercel Blob store."""

    def __init__(self, prefix: str = _DEFAULT_PREFIX):
        self.prefix = prefix.strip("/")

    # ──────────────────────────────────────────────────────────────────────
    # Path helpers
    # ──────────────────────────────────────────────────────────────────────

    def _data_path(self, user_id: int) -> str:
        return f"{self.prefix}/{user_id}/data"

    def _meta_path(self, user_id: int) -> str:
        return f"{self.prefix}/{user_id}/meta.json"

    def _user_prefix(self, user_id: int) -> str:
        # Trailing slash keeps user 123 from matching user 1234
        return f"{self.prefix}/{user_id}/"

    # ──────────────────────────────────────────────────────────────────────
    # Interface (mirrors bot.session_store.SessionStore)
    # ──────────────────────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        """True if the vercel_blob SDK can be imported."""
        try:
            import vercel_blob  # noqa: F401
            return True
        except ImportError:
            return False

    def save(self, user_id: int, filename: str, data: bytes) -> None:
        """Upsert the dataset bytes for a user."""
        try:
            import vercel_blob

            # Session blobs are overwritten on every upload, so skip the SDK's
            # default 1-year CDN cache to avoid ever serving a stale dataset.
            options = {"allowOverwrite": "true", "cacheControlMaxAge": "0"}
            vercel_blob.put(
                self._data_path(user_id),
                data,
                options=options,
                timeout=_UPLOAD_TIMEOUT,
            )
            meta = json.dumps({"filename": filename}).encode("utf-8")
            vercel_blob.put(
                self._meta_path(user_id),
                meta,
                options=options,
                timeout=_UPLOAD_TIMEOUT,
            )
        except Exception as e:
            logger.warning("Failed to persist session for user %s: %s", user_id, e)

    def load(self, user_id: int) -> Optional[Tuple[str, bytes]]:
        """Return (filename, bytes) for a user, or None if no session exists."""
        try:
            import vercel_blob
            import requests

            result = vercel_blob.list({"prefix": self._user_prefix(user_id)})
            blobs = {b.get("pathname"): b for b in result.get("blobs", [])}

            data_blob = blobs.get(self._data_path(user_id))
            if data_blob is None:
                return None

            data_resp = requests.get(data_blob["url"], timeout=_FETCH_TIMEOUT)
            data_resp.raise_for_status()
            data = data_resp.content

            filename = "uploaded_file.csv"
            meta_blob = blobs.get(self._meta_path(user_id))
            if meta_blob is not None:
                try:
                    meta_resp = requests.get(meta_blob["url"], timeout=_FETCH_TIMEOUT)
                    meta_resp.raise_for_status()
                    filename = (
                        json.loads(meta_resp.content.decode("utf-8")).get("filename")
                        or filename
                    )
                except Exception:
                    logger.warning(
                        "Could not read metadata blob for user %s", user_id, exc_info=True
                    )

            return filename, data
        except Exception as e:
            logger.warning("Failed to load session for user %s: %s", user_id, e)
            return None

    def clear(self, user_id: int) -> None:
        """Remove the persisted session for a user (data + metadata blobs)."""
        try:
            import vercel_blob

            result = vercel_blob.list({"prefix": self._user_prefix(user_id)})
            urls = [b.get("url") for b in result.get("blobs", []) if b.get("url")]
            if urls:
                vercel_blob.delete(urls)
        except Exception as e:
            logger.warning("Failed to clear session for user %s: %s", user_id, e)
