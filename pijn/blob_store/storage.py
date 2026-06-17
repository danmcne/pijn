"""
Content-addressed blob storage.

A *blob* is immutable bytes named by its sha256 (SPEC §3). Bytes live as files
named by their hash under `root/`; ownership/size/type metadata lives in a small
SQLite table so we can answer `GET /list/<pubkey>` and enforce delete ownership.

Because the hash *is* the name, integrity is self-verifying and any server is
interchangeable — this is what later makes file-level mirroring (P3) trivial.
"""

import hashlib
import os
import sqlite3
import threading
import time

_SCHEMA = """
CREATE TABLE IF NOT EXISTS blobs (
    sha256      TEXT PRIMARY KEY,
    size        INTEGER NOT NULL,
    type        TEXT NOT NULL DEFAULT '',
    pubkey      TEXT NOT NULL DEFAULT '',   -- uploader, for list/delete
    uploaded_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_blobs_pubkey ON blobs(pubkey);
"""


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class BlobStore:
    def __init__(self, root: str, db_path: str = None):
        self.root = root
        os.makedirs(root, exist_ok=True)
        self._conn = sqlite3.connect(db_path or os.path.join(root, "blobs.sqlite"),
                                     check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def _path(self, sha: str) -> str:
        return os.path.join(self.root, sha)

    # --- writes --------------------------------------------------------------
    def put(self, data: bytes, content_type: str = "", pubkey: str = "") -> dict:
        """Store bytes; return a blob descriptor. Idempotent by content."""
        sha = sha256_hex(data)
        path = self._path(sha)
        if not os.path.exists(path):
            # Write to a temp file then rename, so a partial write never looks
            # like a valid blob.
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO blobs (sha256, size, type, pubkey, uploaded_at)"
                " VALUES (?,?,?,?,?)",
                (sha, len(data), content_type, pubkey, int(time.time())),
            )
            self._conn.commit()
        return self.descriptor(sha)

    def delete(self, sha: str, pubkey: str) -> tuple[bool, str]:
        """Delete a blob the caller owns. Returns (ok, message)."""
        with self._lock:
            row = self._conn.execute("SELECT pubkey FROM blobs WHERE sha256=?", (sha,)).fetchone()
            if row is None:
                return False, "not found"
            if row["pubkey"] and row["pubkey"] != pubkey:
                return False, "not owner"
            self._conn.execute("DELETE FROM blobs WHERE sha256=?", (sha,))
            self._conn.commit()
        try:
            os.remove(self._path(sha))
        except FileNotFoundError:
            pass
        return True, "deleted"

    # --- reads ---------------------------------------------------------------
    def has(self, sha: str) -> bool:
        return os.path.exists(self._path(sha))

    def get(self, sha: str) -> bytes | None:
        try:
            with open(self._path(sha), "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None

    def meta(self, sha: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM blobs WHERE sha256=?", (sha,)).fetchone()
        return dict(row) if row else None

    def total_bytes(self) -> int:
        """Sum of stored blob sizes — used by the replication node-storage ceiling."""
        with self._lock:
            row = self._conn.execute("SELECT COALESCE(SUM(size),0) AS t FROM blobs").fetchone()
        return int(row["t"])

    def entries(self) -> list:
        """All blobs as {sha256, size, uploaded_at} — for eviction strategies."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT sha256, size, uploaded_at FROM blobs"
            ).fetchall()
        return [dict(r) for r in rows]

    def evict(self, sha: str) -> bool:
        """Delete a blob regardless of uploader (replication-controlled eviction)."""
        with self._lock:
            self._conn.execute("DELETE FROM blobs WHERE sha256=?", (sha,))
            self._conn.commit()
        try:
            os.remove(self._path(sha))
        except FileNotFoundError:
            pass
        return True

    def descriptor(self, sha: str, base_url: str = "") -> dict:
        """A Blossom blob descriptor (BUD-02)."""
        m = self.meta(sha) or {}
        return {
            "url": f"{base_url}/{sha}" if base_url else f"/{sha}",
            "sha256": sha,
            "size": m.get("size", 0),
            "type": m.get("type", ""),
            "uploaded": m.get("uploaded_at", 0),
        }

    def list_by_pubkey(self, pubkey: str, base_url: str = "") -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT sha256 FROM blobs WHERE pubkey=? ORDER BY uploaded_at DESC", (pubkey,)
            ).fetchall()
        return [self.descriptor(r["sha256"], base_url) for r in rows]
