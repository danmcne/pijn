"""
Password encryption for the secret key at rest.

**Primary backend: pyca/cryptography** — the standard, audited Python crypto
library. The nsec is sealed with ChaCha20-Poly1305 (RFC 8439 AEAD) under a key
derived from the passphrase with scrypt. Both ship in the `cryptography` wheel,
so there is still no build step.

A pure-Python fallback (`_cipher_fallback.py`) is used **only** if
`cryptography` cannot be imported; it implements the same RFC 8439 / scrypt
construction, so the on-disk container is byte-for-byte identical and a file
written by one backend decrypts under the other. `cipher.BACKEND` reports which
is live.

Container format (JSON):
    {"v":2, "kdf":"scrypt", "n","r","p", "salt","nonce","ct","tag"}  (base64)
The KDF name and parameters are recorded in the container and honored on
decrypt, so a file always re-derives its key the way it was written — no
silent cross-environment mismatch.

Threat model: this protects the nsec if the disk/backup is stolen; scrypt gates
brute force. It is decrypted into memory only when a signing command needs it;
the daemon (`run`) never needs it. This is at-rest protection, not a defence
against a compromised live host.
"""

import base64
import json
import os

# scrypt cost parameters (interactive-grade; tune up for slower-to-brute files).
_N, _R, _P = 1 << 15, 8, 1

BACKEND = "cryptography"

try:
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
        return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(password.encode("utf-8"))

    def _seal(key: bytes, nonce: bytes, plaintext: bytes):
        blob = ChaCha20Poly1305(key).encrypt(nonce, plaintext, None)
        return blob[:-16], blob[-16:]          # (ciphertext, tag)

    def _open(key: bytes, nonce: bytes, ct: bytes, tag: bytes) -> bytes:
        return ChaCha20Poly1305(key).decrypt(nonce, ct + tag, None)

except ImportError:  # pragma: no cover - exercised only without a cryptography wheel
    import sys

    BACKEND = "pure-python"
    print(
        "pijn: warning — `cryptography` not available; falling back to the "
        "pure-Python ChaCha20-Poly1305 + scrypt implementation. Install "
        "`cryptography` for production use.",
        file=sys.stderr,
    )
    from . import _cipher_fallback as _fb

    def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
        return _fb._derive(password, salt, n, r, p)

    def _seal(key: bytes, nonce: bytes, plaintext: bytes):
        return _fb._aead_encrypt(key, nonce, plaintext)

    def _open(key: bytes, nonce: bytes, ct: bytes, tag: bytes) -> bytes:
        return _fb._aead_decrypt(key, nonce, ct, tag)


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def encrypt_secret(secret: bytes, password: str) -> str:
    """Encrypt a secret under a password; return a JSON string to store on disk."""
    salt, nonce = os.urandom(16), os.urandom(12)
    key = _derive(password, salt, _N, _R, _P)
    ct, tag = _seal(key, nonce, secret)
    return json.dumps({
        "v": 2, "kdf": "scrypt", "n": _N, "r": _R, "p": _P,
        "salt": _b64(salt), "nonce": _b64(nonce), "ct": _b64(ct), "tag": _b64(tag),
    })


def decrypt_secret(blob: str, password: str) -> bytes:
    """Decrypt a container produced by `encrypt_secret`. Raises on wrong password.

    The KDF and its parameters are read from the container itself, so a file
    written by either backend (or an earlier v1 file) re-derives the same key.
    """
    d = json.loads(blob)
    if d.get("kdf", "scrypt") != "scrypt":
        raise ValueError(f"unsupported kdf: {d.get('kdf')!r}")
    ub = base64.b64decode
    key = _derive(password, ub(d["salt"]), d.get("n", _N), d.get("r", _R), d.get("p", _P))
    try:
        return _open(key, ub(d["nonce"]), ub(d["ct"]), ub(d["tag"]))
    except Exception as e:  # normalize any backend's auth error to one message
        raise ValueError("authentication failed (wrong password or corrupt file)") from e
