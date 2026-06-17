"""
Event-store persistence (SQLite).

This is the storage half of the relay. It owns one thing: events. It enforces
NIP-01 storage classes:

  * regular      — stored, never replaced
  * replaceable  — only the newest event per (pubkey, kind) is kept
  * addressable  — only the newest per (pubkey, kind, d-tag) is kept
  * ephemeral    — never stored (the relay broadcasts but does not persist)

"Newest" means greatest `created_at`; ties are broken by the lexicographically
smallest id (NIP-01). A single-letter tag index table backs `#x` filters.
"""

import json
import sqlite3
import threading

from ..nostr.event import ADDRESSABLE, EPHEMERAL, REPLACEABLE, Event
from ..nostr.filters import _tag_filters

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY,
    pubkey      TEXT NOT NULL,
    created_at  INTEGER NOT NULL,
    kind        INTEGER NOT NULL,
    d_tag       TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL,
    tags        TEXT NOT NULL,   -- JSON
    sig         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_pubkey  ON events(pubkey);
CREATE INDEX IF NOT EXISTS idx_events_kind    ON events(kind);
CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
CREATE INDEX IF NOT EXISTS idx_events_addr    ON events(pubkey, kind, d_tag);

CREATE TABLE IF NOT EXISTS event_tags (
    event_id  TEXT NOT NULL,
    name      TEXT NOT NULL,   -- single-letter tag name
    value     TEXT NOT NULL,
    PRIMARY KEY (event_id, name, value),
    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_tags_name_value ON event_tags(name, value);
"""


class EventStore:
    """Thread-safe wrapper around a single SQLite database file."""

    def __init__(self, path: str):
        self.path = path
        # check_same_thread=False + a lock lets the relay (async) and the
        # gateway resolver (sync read) share one connection safely.
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self):
        self._conn.close()

    # --- writing -------------------------------------------------------------
    def store(self, event: Event) -> tuple[bool, str]:
        """Persist an event, applying replaceable/addressable rules.

        Returns (accepted, message). Ephemeral events return (True, "ephemeral")
        without being written. Duplicates and superseded replacements return
        (True, ...) too — the relay treats them as accepted-but-noop.
        """
        cls = event.event_class
        if cls == EPHEMERAL:
            return True, "ephemeral"

        with self._lock:
            cur = self._conn.cursor()
            # Duplicate id?
            if cur.execute("SELECT 1 FROM events WHERE id=?", (event.id,)).fetchone():
                return True, "duplicate"

            if cls in (REPLACEABLE, ADDRESSABLE):
                if cls == REPLACEABLE:
                    rows = cur.execute(
                        "SELECT id, created_at FROM events WHERE pubkey=? AND kind=?",
                        (event.pubkey, event.kind),
                    ).fetchall()
                else:
                    rows = cur.execute(
                        "SELECT id, created_at FROM events WHERE pubkey=? AND kind=? AND d_tag=?",
                        (event.pubkey, event.kind, event.d_tag),
                    ).fetchall()
                for row in rows:
                    # Keep the newer event; tie-break on smallest id.
                    if (row["created_at"], row["id"]) >= (event.created_at, event.id):
                        return True, "superseded"
                # Incoming event wins: drop the older ones.
                for row in rows:
                    self._delete(cur, row["id"])

            self._insert(cur, event)
            self._conn.commit()
            return True, "stored"

    def _insert(self, cur, event: Event):
        cur.execute(
            "INSERT INTO events (id, pubkey, created_at, kind, d_tag, content, tags, sig)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                event.id, event.pubkey, event.created_at, event.kind, event.d_tag,
                event.content, json.dumps(event.tags, separators=(",", ":")), event.sig,
            ),
        )
        for t in event.tags:
            if t and len(t) >= 2 and len(t[0]) == 1:
                cur.execute(
                    "INSERT OR IGNORE INTO event_tags (event_id, name, value) VALUES (?,?,?)",
                    (event.id, t[0], t[1]),
                )

    def _delete(self, cur, event_id: str):
        cur.execute("DELETE FROM event_tags WHERE event_id=?", (event_id,))
        cur.execute("DELETE FROM events WHERE id=?", (event_id,))

    # --- reading -------------------------------------------------------------
    def query(self, filters: list) -> list:
        """Return events matching ANY of the given NIP-01 filters, newest first.

        Each filter's `limit` caps that filter's contribution; results are
        merged and de-duplicated across filters.
        """
        seen, out = set(), []
        with self._lock:
            for flt in filters:
                for ev in self._query_one(flt):
                    if ev.id not in seen:
                        seen.add(ev.id)
                        out.append(ev)
        out.sort(key=lambda e: e.created_at, reverse=True)
        return out

    def _query_one(self, flt: dict) -> list:
        where, params = [], []
        if "ids" in flt:
            where.append(f"id IN ({','.join('?' * len(flt['ids']))})")
            params += flt["ids"]
        if "authors" in flt:
            where.append(f"pubkey IN ({','.join('?' * len(flt['authors']))})")
            params += flt["authors"]
        if "kinds" in flt:
            where.append(f"kind IN ({','.join('?' * len(flt['kinds']))})")
            params += flt["kinds"]
        if "since" in flt:
            where.append("created_at >= ?")
            params.append(flt["since"])
        if "until" in flt:
            where.append("created_at <= ?")
            params.append(flt["until"])

        # Single-letter tag conditions become an INTERSECT over the tag index:
        # the event must carry at least one matching value for EACH #x present.
        tag_clauses = []
        for letter, values in _tag_filters(flt):
            placeholders = ",".join("?" * len(values))
            tag_clauses.append(
                ("id IN (SELECT event_id FROM event_tags WHERE name=? AND value IN "
                 f"({placeholders}))", [letter, *values])
            )
        for clause, clause_params in tag_clauses:
            where.append(clause)
            params += clause_params

        sql = "SELECT * FROM events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC, id ASC"
        if "limit" in flt:
            sql += " LIMIT ?"
            params.append(int(flt["limit"]))

        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_event(r) for r in rows]

    @staticmethod
    def _row_to_event(row) -> Event:
        return Event(
            id=row["id"], pubkey=row["pubkey"], created_at=row["created_at"],
            kind=row["kind"], content=row["content"],
            tags=json.loads(row["tags"]), sig=row["sig"],
        )

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"]
