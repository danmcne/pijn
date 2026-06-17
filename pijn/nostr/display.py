"""
Name display helpers.

The rule (SPEC §7): a claimed name is never shown on its own. Because display
names are unverified free text, anyone can call themselves "Alice"; the only
thing that *can't* be forged is the npub. So every surface that renders a name
shows a short, key-derived digest of the npub beside it — enough to tell two
"Alice"s apart at a glance and to spot a swapped identity, without making the
user read 63 characters.

`short_npub` is the digest (a truncation of the npub itself, which is already a
deterministic encoding of the public key — a "known digest" in the sense you can
recompute it from the key). `name_badge` is the default composition the
templates and the gateway paybar use; callers may render their own.
"""

from . import bech32


def short_npub(value: str, head: int = 8, tail: int = 4) -> str:
    """`npub1abcd…wx9z` — a recognizable, key-derived digest of an identity.

    Accepts an npub or a 64-char hex pubkey. `head` counts from the start of the
    full npub (so the `npub1` prefix is included); `tail` from the end.
    """
    npub = value if value.startswith("npub1") else bech32.to_npub(bech32.normalize_pubkey(value))
    if len(npub) <= head + tail + 1:
        return npub
    return f"{npub[:head]}…{npub[-tail:]}"


def name_badge(npub_or_hex: str, claimed_name: str = "",
               nip05: str = "", nip05_verified: bool = False) -> str:
    """Default rendering of an identity: name (if any), NIP-05 mark, npub digest.

    Examples:
        Alice ✓good.org · npub1abcd…wx9z      (verified NIP-05)
        Alice ?evil.com · npub1abcd…wx9z      (claimed but unverified NIP-05)
        Alice · npub1abcd…wx9z                (no NIP-05)
        npub1abcd…wx9z                        (no claimed name)

    The digest is always present; the name and NIP-05 are decoration on top of
    the one thing that can't be faked.
    """
    digest = short_npub(npub_or_hex)
    parts = []
    if claimed_name:
        parts.append(claimed_name.strip())
    if nip05:
        mark = "✓" if nip05_verified else "?"
        # `_@domain` already collapses to the bare domain upstream.
        parts.append(f"{mark}{nip05}")
    label = " ".join(parts)
    return f"{label} · {digest}" if label else digest
