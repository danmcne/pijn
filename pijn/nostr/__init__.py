"""pijn's Nostr core: keys, events, filters.

Signatures use libsecp256k1 (via `coincurve`) and at-rest key encryption uses
pyca/cryptography — both audited, both shipped as wheels (no build step). Each
has a pure-Python fallback used only when its wheel is unavailable.
"""

from .event import (
    ADDRESSABLE,
    EPHEMERAL,
    Event,
    REGULAR,
    REPLACEABLE,
    classify,
    make_event,
)
from .filters import matches, matches_any
from .keys import Keypair
from .display import name_badge, short_npub
from .nip05 import display_name, parse_nip05, resolve_nip05, verify_nip05

__all__ = [
    "Keypair",
    "Event",
    "make_event",
    "classify",
    "matches",
    "matches_any",
    "EPHEMERAL",
    "REPLACEABLE",
    "ADDRESSABLE",
    "REGULAR",
    "short_npub",
    "name_badge",
    "parse_nip05",
    "display_name",
    "resolve_nip05",
    "verify_nip05",
]
