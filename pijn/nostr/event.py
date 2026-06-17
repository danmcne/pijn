"""
The Nostr event (NIP-01).

An *event* is the only thing that lives on a relay: a signed JSON object owned
by a pubkey. In pijn an event plays one of three roles (see SPEC §3):
pointer/manifest, revision, or application content. This module is the
canonical implementation of event id computation, signing and verification, plus
the NIP-01 classification (regular / replaceable / addressable / ephemeral) the
event-store needs to decide how to persist it.
"""

import hashlib
import json
import time
from dataclasses import dataclass, field

from .schnorr import pubkey_from_seckey, schnorr_sign, schnorr_verify

# NIP-01 event-kind classes. The event-store persists each class differently.
EPHEMERAL = "ephemeral"        # 20000..29999  — never stored
REPLACEABLE = "replaceable"    # 0, 3, 10000..19999 — one per (pubkey, kind)
ADDRESSABLE = "addressable"    # 30000..39999 — one per (pubkey, kind, d-tag)
REGULAR = "regular"            # everything else — stored, never replaced


def classify(kind: int) -> str:
    if 20000 <= kind < 30000:
        return EPHEMERAL
    if kind in (0, 3) or 10000 <= kind < 20000:
        return REPLACEABLE
    if 30000 <= kind < 40000:
        return ADDRESSABLE
    return REGULAR


def serialize_for_id(pubkey, created_at, kind, tags, content) -> bytes:
    """NIP-01 canonical form used to compute the id: a compact JSON array
    `[0, pubkey, created_at, kind, tags, content]` with no extra whitespace."""
    arr = [0, pubkey, created_at, kind, tags, content]
    return json.dumps(arr, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


@dataclass
class Event:
    pubkey: str
    created_at: int
    kind: int
    tags: list
    content: str
    id: str = ""
    sig: str = ""

    # --- tag helpers ---
    def first_tag(self, name: str):
        """Return the value of the first tag with this name, or None."""
        for t in self.tags:
            if t and t[0] == name:
                return t[1] if len(t) > 1 else ""
        return None

    def tag_values(self, name: str):
        """Return all values for tags with this name."""
        return [t[1] for t in self.tags if t and t[0] == name and len(t) > 1]

    @property
    def d_tag(self):
        """The `d` identifier used by addressable events (default empty string)."""
        v = self.first_tag("d")
        return v if v is not None else ""

    @property
    def event_class(self) -> str:
        return classify(self.kind)

    # --- id / signing ---
    def compute_id(self) -> str:
        digest = hashlib.sha256(
            serialize_for_id(self.pubkey, self.created_at, self.kind, self.tags, self.content)
        )
        return digest.hexdigest()

    def sign(self, seckey_bytes: bytes) -> "Event":
        """Set pubkey from the key, compute the id, and attach a BIP-340
        signature. Mutates and returns self."""
        self.pubkey = pubkey_from_seckey(seckey_bytes).hex()
        self.id = self.compute_id()
        self.sig = schnorr_sign(bytes.fromhex(self.id), seckey_bytes).hex()
        return self

    def verify(self) -> bool:
        """True iff the id matches the content and the signature is valid."""
        if self.id != self.compute_id():
            return False
        try:
            return schnorr_verify(
                bytes.fromhex(self.id), bytes.fromhex(self.pubkey), bytes.fromhex(self.sig)
            )
        except (ValueError, TypeError):
            return False

    # --- (de)serialization ---
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "pubkey": self.pubkey,
            "created_at": self.created_at,
            "kind": self.kind,
            "tags": self.tags,
            "content": self.content,
            "sig": self.sig,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        return cls(
            pubkey=d["pubkey"],
            created_at=int(d["created_at"]),
            kind=int(d["kind"]),
            tags=d.get("tags", []),
            content=d.get("content", ""),
            id=d.get("id", ""),
            sig=d.get("sig", ""),
        )


def make_event(kind: int, content: str, tags=None, created_at=None) -> Event:
    """Build an unsigned event (caller fills pubkey via sign())."""
    return Event(
        pubkey="",
        created_at=created_at if created_at is not None else int(time.time()),
        kind=kind,
        tags=tags or [],
        content=content,
    )
