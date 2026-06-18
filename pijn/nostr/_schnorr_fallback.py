"""
Pure-Python BIP-340 Schnorr — *fallback only*.

Used by `schnorr.py` only when libsecp256k1 (coincurve) is unavailable.

Nostr signs every event with a BIP-340 Schnorr signature over the event id,
using a 32-byte x-only public key. We vendor a pure-Python implementation
(adapted from the public-domain BIP-340 reference) so the node has *no native
crypto dependency* and therefore no build step — matching pijn's local-first,
minimal-dependency stance.

Tradeoff: pure-Python point arithmetic is slow (~ms per verify). That is fine
for a personal v1 node. A public, high-throughput node can drop in a C binding
(e.g. coincurve) behind this same `schnorr_sign` / `schnorr_verify` interface —
the same "build for v1, keep the option open" decision we made for the relay.

This module deliberately exposes only two functions; everything else is the
field/curve math they need.
"""

import hashlib

# secp256k1 domain parameters.
_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_G = (
    0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
)

Point = tuple  # (x, y) or None for the point at infinity.


def _tagged_hash(tag: str, msg: bytes) -> bytes:
    """BIP-340 tagged hash: sha256(sha256(tag) || sha256(tag) || msg)."""
    th = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(th + th + msg).digest()


def _is_infinite(p):
    return p is None


def _x(p):
    return p[0]


def _y(p):
    return p[1]


def _point_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    if _x(p1) == _x(p2) and _y(p1) != _y(p2):
        return None  # P + (-P) = infinity
    if p1 == p2:
        lam = (3 * _x(p1) * _x(p1) * pow(2 * _y(p1), _P - 2, _P)) % _P
    else:
        lam = ((_y(p2) - _y(p1)) * pow(_x(p2) - _x(p1), _P - 2, _P)) % _P
    x3 = (lam * lam - _x(p1) - _x(p2)) % _P
    y3 = (lam * (_x(p1) - x3) - _y(p1)) % _P
    return (x3, y3)


def _point_mul(p, n):
    """Scalar multiply via double-and-add."""
    r = None
    for i in range(256):
        if (n >> i) & 1:
            r = _point_add(r, p)
        p = _point_add(p, p)
    return r


def _has_even_y(p):
    return _y(p) % 2 == 0


def _lift_x(x: int):
    """Recover the even-y curve point with the given x coordinate, or None."""
    if x >= _P:
        return None
    c = (pow(x, 3, _P) + 7) % _P
    y = pow(c, (_P + 1) // 4, _P)
    if pow(y, 2, _P) != c:
        return None
    return (x, y if y % 2 == 0 else _P - y)


def _int(b: bytes) -> int:
    return int.from_bytes(b, "big")


def _bytes(n: int) -> bytes:
    return n.to_bytes(32, "big")


def pubkey_from_seckey(seckey: bytes) -> bytes:
    """Derive the 32-byte x-only public key from a 32-byte secret key."""
    d0 = _int(seckey)
    if not (1 <= d0 <= _N - 1):
        raise ValueError("secret key out of range")
    P = _point_mul(_G, d0)
    return _bytes(_x(P))


def schnorr_sign(msg: bytes, seckey: bytes, aux_rand: bytes = b"\x00" * 32) -> bytes:
    """Produce a 64-byte BIP-340 signature over `msg` (typically a 32-byte id)."""
    d0 = _int(seckey)
    if not (1 <= d0 <= _N - 1):
        raise ValueError("secret key out of range")
    P = _point_mul(_G, d0)
    d = d0 if _has_even_y(P) else _N - d0
    t = (d ^ _int(_tagged_hash("BIP0340/aux", aux_rand))).to_bytes(32, "big")
    rand = _tagged_hash("BIP0340/nonce", t + _bytes(_x(P)) + msg)
    k0 = _int(rand) % _N
    if k0 == 0:
        raise RuntimeError("nonce is zero (negligible probability)")
    R = _point_mul(_G, k0)
    k = k0 if _has_even_y(R) else _N - k0
    e = _int(_tagged_hash("BIP0340/challenge", _bytes(_x(R)) + _bytes(_x(P)) + msg)) % _N
    return _bytes(_x(R)) + _bytes((k + e * d) % _N)


def schnorr_verify(msg: bytes, pubkey: bytes, sig: bytes) -> bool:
    """Verify a 64-byte BIP-340 signature. Returns True iff valid."""
    if len(pubkey) != 32 or len(sig) != 64:
        return False
    P = _lift_x(_int(pubkey))
    if P is None:
        return False
    r = _int(sig[:32])
    s = _int(sig[32:])
    if r >= _P or s >= _N:
        return False
    e = _int(_tagged_hash("BIP0340/challenge", sig[:32] + pubkey + msg)) % _N
    R = _point_add(_point_mul(_G, s), _point_mul(P, _N - e))
    if R is None or not _has_even_y(R) or _x(R) != r:
        return False
    return True
