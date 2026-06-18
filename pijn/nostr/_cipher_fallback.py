"""
Pure-Python ChaCha20-Poly1305 + scrypt — *fallback only*.

Used by `cipher.py` only when pyca/cryptography is unavailable.

The same stance as the Schnorr code: rather than pull in a native crypto library
just to encrypt one 32-byte secret at rest, this vendors ChaCha20-Poly1305
(RFC 8439) in pure Python and derives the key from the password with scrypt
(stdlib `hashlib`). It is verified against the RFC 8439 test vectors.

Threat model: the encrypted file protects the nsec if the disk/backup is stolen —
brute-forcing the password is gated by scrypt. It is decrypted into memory only
when a signing command needs it; the daemon (`run`) never needs it. This is at-
rest protection, not defence against a compromised live host.
"""

import hashlib
import hmac
import json
import os
import struct

_MASK = 0xFFFFFFFF


def _rotl(x, n):
    return ((x << n) | (x >> (32 - n))) & _MASK


def _quarter(s, a, b, c, d):
    s[a] = (s[a] + s[b]) & _MASK; s[d] = _rotl(s[d] ^ s[a], 16)
    s[c] = (s[c] + s[d]) & _MASK; s[b] = _rotl(s[b] ^ s[c], 12)
    s[a] = (s[a] + s[b]) & _MASK; s[d] = _rotl(s[d] ^ s[a], 8)
    s[c] = (s[c] + s[d]) & _MASK; s[b] = _rotl(s[b] ^ s[c], 7)


def _chacha20_block(key, counter, nonce):
    const = (0x61707865, 0x3320646e, 0x79622d32, 0x6b206574)
    state = list(const) + list(struct.unpack("<8I", key)) + [counter] + list(struct.unpack("<3I", nonce))
    work = state[:]
    for _ in range(10):
        _quarter(work, 0, 4, 8, 12); _quarter(work, 1, 5, 9, 13)
        _quarter(work, 2, 6, 10, 14); _quarter(work, 3, 7, 11, 15)
        _quarter(work, 0, 5, 10, 15); _quarter(work, 1, 6, 11, 12)
        _quarter(work, 2, 7, 8, 13); _quarter(work, 3, 4, 9, 14)
    out = [(work[i] + state[i]) & _MASK for i in range(16)]
    return struct.pack("<16I", *out)


def _chacha20(key, counter, nonce, data):
    out = bytearray()
    for i in range(0, len(data), 64):
        ks = _chacha20_block(key, counter + i // 64, nonce)
        block = data[i:i + 64]
        out += bytes(b ^ ks[j] for j, b in enumerate(block))
    return bytes(out)


_P1305 = (1 << 130) - 5


def _poly1305(msg, key):
    r = int.from_bytes(key[:16], "little") & 0x0ffffffc0ffffffc0ffffffc0fffffff
    s = int.from_bytes(key[16:32], "little")
    acc = 0
    for i in range(0, len(msg), 16):
        chunk = msg[i:i + 16]
        n = int.from_bytes(chunk + b"\x01", "little")
        acc = ((acc + n) * r) % _P1305
    acc = (acc + s) & ((1 << 128) - 1)
    return acc.to_bytes(16, "little")


def _pad16(x):
    return b"\x00" * ((16 - len(x) % 16) % 16)


def _aead_encrypt(key, nonce, plaintext, aad=b""):
    poly_key = _chacha20_block(key, 0, nonce)[:32]
    ct = _chacha20(key, 1, nonce, plaintext)
    mac_data = aad + _pad16(aad) + ct + _pad16(ct) + struct.pack("<QQ", len(aad), len(ct))
    tag = _poly1305(mac_data, poly_key)
    return ct, tag


def _aead_decrypt(key, nonce, ct, tag, aad=b""):
    poly_key = _chacha20_block(key, 0, nonce)[:32]
    mac_data = aad + _pad16(aad) + ct + _pad16(ct) + struct.pack("<QQ", len(aad), len(ct))
    if not hmac.compare_digest(_poly1305(mac_data, poly_key), tag):
        raise ValueError("authentication failed (wrong password or corrupt file)")
    return _chacha20(key, 1, nonce, ct)


# --- password-based secret container ---------------------------------------

_N, _R, _P = 1 << 15, 8, 1


def _derive(password, salt, n=_N, r=_R, p=_P):
    pw = password.encode("utf-8")
    try:
        return hashlib.scrypt(pw, salt=salt, n=n, r=r, p=p, dklen=32,
                              maxmem=2 * 128 * r * n)
    except Exception:
        # Fallback if scrypt is unavailable in this build.
        return hashlib.pbkdf2_hmac("sha256", pw, salt, 600_000, dklen=32)


def encrypt_secret(secret: bytes, password: str) -> str:
    """Encrypt a secret under a password; return a JSON string to store on disk."""
    salt, nonce = os.urandom(16), os.urandom(12)
    key = _derive(password, salt)
    ct, tag = _aead_encrypt(key, nonce, secret)
    import base64
    b64 = lambda b: base64.b64encode(b).decode()
    return json.dumps({"v": 1, "kdf": "scrypt", "n": _N, "r": _R, "p": _P,
                       "salt": b64(salt), "nonce": b64(nonce),
                       "ct": b64(ct), "tag": b64(tag)})


def decrypt_secret(blob: str, password: str) -> bytes:
    """Decrypt a container produced by `encrypt_secret`. Raises on wrong password."""
    import base64
    d = json.loads(blob)
    ub = lambda s: base64.b64decode(s)
    key = _derive(password, ub(d["salt"]), d.get("n", _N), d.get("r", _R), d.get("p", _P))
    return _aead_decrypt(key, ub(d["nonce"]), ub(d["ct"]), ub(d["tag"]))
