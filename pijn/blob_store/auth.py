"""
Blossom authorization (kind 24242).

Blossom is *not* a NIP; it is the BUD series of HTTP endpoints (SPEC §1). Writes
(and optionally reads) are authorized by a signed kind-24242 Nostr event passed
in the HTTP header:

    Authorization: Nostr <base64(event-json)>

The event must:
  * be kind 24242 with a valid signature,
  * carry a `t` tag whose value matches the requested verb
    (upload / get / delete / list),
  * carry a NIP-40 `expiration` tag in the future,
  * for upload/get/delete: carry an `x` tag matching the blob's sha256.

`verify_auth` returns the authenticated pubkey on success, else None.
"""

import base64
import json
import time

from ..nostr.event import Event


def parse_auth_header(header_value: str) -> Event | None:
    """Decode an `Authorization: Nostr <base64>` header into an Event."""
    if not header_value:
        return None
    parts = header_value.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "nostr":
        return None
    try:
        decoded = base64.b64decode(parts[1])
        return Event.from_dict(json.loads(decoded))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def verify_auth(header_value: str, verb: str, sha: str | None = None) -> str | None:
    """Validate a Blossom auth header for `verb` (+ optional blob `sha`).

    Returns the signer's pubkey hex if the token authorizes the action, else None.
    """
    event = parse_auth_header(header_value)
    if event is None or event.kind != 24242:
        return None
    if not event.verify():
        return None
    if event.first_tag("t") != verb:
        return None

    expiration = event.first_tag("expiration")
    if expiration is None:
        return None
    try:
        if int(expiration) <= int(time.time()):
            return None  # expired
    except ValueError:
        return None

    # Verbs that act on a specific blob must name it in an `x` tag.
    if sha is not None and verb in ("upload", "get", "delete"):
        if sha not in event.tag_values("x"):
            return None

    return event.pubkey
