"""
BIP-340 Schnorr signatures over secp256k1 — Nostr's event signature scheme.

**Primary backend: libsecp256k1 via `coincurve`.** This is the same audited,
constant-time C library Bitcoin Core uses; it is the industry standard for
secp256k1 and ships as a pre-built wheel, so installing it needs no compiler and
keeps pijn's "no build step" property. We do *not* hand-roll the curve math on
the hot path: signing and verification go through libsecp256k1.

A pure-Python fallback (`_schnorr_fallback.py`, BIP-340 reference math) is used
**only** when `coincurve` cannot be imported — e.g. an exotic platform with no
wheel. It is correct (checked against the BIP-340 vectors) but not constant-time,
so it emits a one-time warning. Check `schnorr.BACKEND` to see which is active.

Public surface is two functions plus a key-derivation helper; callers
(`event.py`, `keys.py`) never need to know which backend is live.
"""

import os
import sys

BACKEND = "coincurve"

try:
    from coincurve import PrivateKey as _PrivateKey
    from coincurve import PublicKeyXOnly as _PublicKeyXOnly

    def pubkey_from_seckey(seckey: bytes) -> bytes:
        """Derive the 32-byte x-only public key from a 32-byte secret key."""
        # libsecp256k1 validates the scalar range; .format() is the compressed
        # SEC1 point, whose first byte is the parity prefix — drop it for x-only.
        return _PrivateKey(seckey).public_key.format(compressed=True)[1:]

    def schnorr_sign(msg: bytes, seckey: bytes, aux_rand: bytes = b"\x00" * 32) -> bytes:
        """Produce a 64-byte BIP-340 signature over `msg` (typically a 32-byte id)."""
        return _PrivateKey(seckey).sign_schnorr(msg, aux_rand)

    def schnorr_verify(msg: bytes, pubkey: bytes, sig: bytes) -> bool:
        """Verify a 64-byte BIP-340 signature. Returns True iff valid."""
        if len(pubkey) != 32 or len(sig) != 64:
            return False
        try:
            return _PublicKeyXOnly(pubkey).verify(sig, msg)
        except Exception:
            return False

except ImportError:  # pragma: no cover - exercised only without a coincurve wheel
    BACKEND = "pure-python"
    print(
        "pijn: warning — `coincurve` (libsecp256k1) not available; falling back to "
        "the pure-Python BIP-340 implementation. It is correct but slower and not "
        "constant-time. Install `coincurve` for production use.",
        file=sys.stderr,
    )
    from ._schnorr_fallback import (  # noqa: F401
        pubkey_from_seckey,
        schnorr_sign,
        schnorr_verify,
    )
