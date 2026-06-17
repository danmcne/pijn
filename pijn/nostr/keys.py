"""
Key management.

A pijn identity is a secp256k1 keypair. The secret key (`nsec`) is the crown
jewel: it never leaves the host and is never exposed to the gateway or any
server. This module only deals in generating keys and deriving the public key;
signing lives next to the data being signed (events, blob-auth tokens).
"""

import os

from . import bech32
from .schnorr import pubkey_from_seckey


class Keypair:
    """A secp256k1 keypair, stored as hex internally."""

    def __init__(self, seckey_hex: str):
        self.seckey_hex = seckey_hex
        self.pubkey_hex = pubkey_from_seckey(bytes.fromhex(seckey_hex)).hex()

    # --- constructors ---
    @classmethod
    def generate(cls) -> "Keypair":
        """Generate a fresh keypair from OS randomness."""
        return cls(os.urandom(32).hex())

    @classmethod
    def from_nsec(cls, nsec: str) -> "Keypair":
        return cls(bech32.from_nsec(nsec))

    @classmethod
    def from_hex(cls, seckey_hex: str) -> "Keypair":
        return cls(seckey_hex)

    # --- views ---
    @property
    def npub(self) -> str:
        return bech32.to_npub(self.pubkey_hex)

    @property
    def nsec(self) -> str:
        return bech32.to_nsec(self.seckey_hex)

    @property
    def seckey_bytes(self) -> bytes:
        return bytes.fromhex(self.seckey_hex)
