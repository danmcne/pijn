"""
bech32 encoding (NIP-19 `npub` / `nsec`).

Nostr keys are 32-byte values. Humans exchange them as bech32 strings with a
human-readable prefix: `npub1...` for public keys, `nsec1...` for secret keys.
This is the plain bech32 algorithm (BIP-173), not bech32m. Adapted from the
public-domain reference implementation.

We keep this tiny and dependency-free; only the four helpers at the bottom
(`to_npub`, `to_nsec`, `from_npub`, `from_nsec`) are used elsewhere.
"""

_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _polymod(values):
    generator = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= generator[i] if ((top >> i) & 1) else 0
    return chk


def _hrp_expand(hrp):
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _verify_checksum(hrp, data):
    return _polymod(_hrp_expand(hrp) + data) == 1


def _create_checksum(hrp, data):
    values = _hrp_expand(hrp) + data
    polymod = _polymod(values + [0, 0, 0, 0, 0, 0]) ^ 1
    return [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]


def _convertbits(data, frombits, tobits, pad=True):
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    for value in data:
        if value < 0 or (value >> frombits):
            return None
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (tobits - bits)) & maxv)
    elif not pad and (bits >= frombits or ((acc << (tobits - bits)) & maxv)):
        return None
    return ret


def bech32_encode(hrp, data_bytes: bytes) -> str:
    data = _convertbits(list(data_bytes), 8, 5)
    combined = data + _create_checksum(hrp, data)
    return hrp + "1" + "".join(_CHARSET[d] for d in combined)


def bech32_decode(bech: str):
    """Return (hrp, payload_bytes) or raise ValueError."""
    if bech != bech.lower() and bech != bech.upper():
        raise ValueError("mixed case bech32")
    bech = bech.lower()
    pos = bech.rfind("1")
    if pos < 1 or pos + 7 > len(bech):
        raise ValueError("malformed bech32")
    hrp = bech[:pos]
    try:
        data = [_CHARSET.index(c) for c in bech[pos + 1:]]
    except ValueError:
        raise ValueError("invalid bech32 character")
    if not _verify_checksum(hrp, data):
        raise ValueError("bad bech32 checksum")
    payload = _convertbits(data[:-6], 5, 8, False)
    if payload is None:
        raise ValueError("invalid bech32 payload")
    return hrp, bytes(payload)


# --- NIP-19 convenience wrappers (the only public surface used elsewhere) ---

def to_npub(pubkey_hex: str) -> str:
    return bech32_encode("npub", bytes.fromhex(pubkey_hex))


def to_nsec(seckey_hex: str) -> str:
    return bech32_encode("nsec", bytes.fromhex(seckey_hex))


def from_npub(npub: str) -> str:
    hrp, data = bech32_decode(npub)
    if hrp != "npub":
        raise ValueError(f"expected npub, got {hrp}")
    return data.hex()


def from_nsec(nsec: str) -> str:
    hrp, data = bech32_decode(nsec)
    if hrp != "nsec":
        raise ValueError(f"expected nsec, got {hrp}")
    return data.hex()


def normalize_pubkey(value: str) -> str:
    """Accept either an npub or a 64-char hex pubkey; return hex."""
    value = value.strip()
    if value.startswith("npub1"):
        return from_npub(value)
    if len(value) == 64:
        int(value, 16)  # validate hex
        return value
    raise ValueError(f"not a pubkey: {value!r}")
