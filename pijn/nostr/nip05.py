"""
NIP-05 — human-readable names backed by a domain.

A NIP-05 identifier looks like `alice@example.com`. It is *not* a globally
unique name and it does not, by itself, prevent impersonation: it only lets a
domain vouch that "the alice here is this pubkey." Trust in the name is exactly
trust in the domain — the same model as email. pijn uses it as the *pump primer*
for a web-of-trust (SPEC §7): a verified NIP-05 plus a set of trusted relays
seeds the graph; ranking and the always-shown npub digest do the rest.

Resolution: GET `https://<domain>/.well-known/nostr.json?name=<local>` and read
`names[local] -> pubkey` (and the optional `relays[pubkey] -> [...]` outbox
hint). Per the spec we do *not* follow HTTP redirects — a redirect could point
the lookup at a domain the operator never vouched for.

This module owns only resolution and verification; it never decides trust. The
caller combines a verified NIP-05 with the trust graph.
"""

import re

import httpx

from .bech32 import normalize_pubkey

# NIP-05 local-part grammar: a-z, 0-9, and - _ . (case-insensitive). `_` is the
# special "root" local part, rendered as the bare domain.
_LOCAL_RE = re.compile(r"^[a-z0-9\-_.]+$", re.IGNORECASE)


def parse_nip05(identifier: str) -> tuple[str, str]:
    """Split `local@domain` into (local, domain). A bare `domain` means `_@domain`."""
    identifier = identifier.strip().lower()
    if "@" in identifier:
        local, domain = identifier.split("@", 1)
    else:
        local, domain = "_", identifier
    if not local or not domain or not _LOCAL_RE.match(local) or "." not in domain:
        raise ValueError(f"not a NIP-05 identifier: {identifier!r}")
    return local, domain


def display_name(identifier: str) -> str:
    """How a NIP-05 should be shown: `_@domain` collapses to just `domain`."""
    local, domain = parse_nip05(identifier)
    return domain if local == "_" else f"{local}@{domain}"


async def resolve_nip05(identifier: str, timeout: float = 8) -> dict | None:
    """Resolve a NIP-05 to {'pubkey': hex, 'relays': [...]} or None.

    `relays` is the optional outbox hint the domain published for this pubkey;
    it is where the resolver can start looking for the identity's events.
    """
    local, domain = parse_nip05(identifier)
    url = f"https://{domain}/.well-known/nostr.json"
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            resp = await client.get(url, params={"name": local})
            resp.raise_for_status()
            doc = resp.json()
    except (httpx.HTTPError, ValueError):
        return None

    names = doc.get("names") or {}
    pubkey = names.get(local)
    if not isinstance(pubkey, str) or len(pubkey) != 64:
        return None
    try:
        int(pubkey, 16)
    except ValueError:
        return None
    relays = (doc.get("relays") or {}).get(pubkey, [])
    return {"pubkey": pubkey, "relays": list(relays) if isinstance(relays, list) else []}


async def verify_nip05(identifier: str, pubkey: str, timeout: float = 8) -> bool:
    """True iff `domain` vouches that `identifier` maps to `pubkey`.

    `pubkey` may be hex or an npub; this is the anti-impersonation check — it
    confirms the claim, it does not establish that the domain is trustworthy.
    """
    try:
        want = normalize_pubkey(pubkey)
    except ValueError:
        return False
    resolved = await resolve_nip05(identifier, timeout=timeout)
    return resolved is not None and resolved["pubkey"] == want
