"""
Identity & data home.

All persistent data lives under ~/.pijn (override with `PIJN_HOME`), partitioned
by operator identity:

    ~/.pijn/
      active                # plaintext: the npub this node uses by default
      <npub>/
        npub                # plaintext (public; readable without the password)
        nsec.enc            # password-encrypted secret key (nostr/cipher.py)
        relay.sqlite        # the node's event store (own + mirrored events)
        blobs/              # the node's blob store (own + mirrored blobs)
        bandwidth.json      # replication bandwidth meter

Upgrading or reinstalling the code never touches this directory, and one machine
can host several node identities side by side. The npub is plaintext by design
(public, and often needed immediately); the nsec is only ever on disk encrypted.

A signing command obtains the key via `load_active_keypair`, which prefers the
`PIJN_NSEC` env var (automation), then decrypts `nsec.enc` using `PIJN_PASSPHRASE`
or an interactive prompt. The daemon (`run`) never needs the key.
"""

import getpass
import os

from .nostr import cipher
from .nostr.keys import Keypair


def pijn_home() -> str:
    return os.environ.get("PIJN_HOME") or os.path.expanduser("~/.pijn")


def identity_dir(npub: str) -> str:
    return os.path.join(pijn_home(), npub)


def active_npub() -> str:
    """The npub this node uses: PIJN_NPUB, else ~/.pijn/active, else ''."""
    npub = os.environ.get("PIJN_NPUB")
    if npub:
        return npub.strip()
    path = os.path.join(pijn_home(), "active")
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    return ""


def set_active(npub: str):
    os.makedirs(pijn_home(), exist_ok=True)
    with open(os.path.join(pijn_home(), "active"), "w") as f:
        f.write(npub + "\n")


def list_identities() -> list:
    home = pijn_home()
    if not os.path.isdir(home):
        return []
    return sorted(d for d in os.listdir(home)
                  if d.startswith("npub1")
                  and os.path.isfile(os.path.join(home, d, "nsec.enc")))


def has_encrypted_key(npub: str) -> bool:
    return bool(npub) and os.path.isfile(os.path.join(identity_dir(npub), "nsec.enc"))


def save_identity(kp: Keypair, password: str, make_active: bool = True) -> str:
    """Write <npub>/npub (plaintext) and <npub>/nsec.enc (encrypted)."""
    d = identity_dir(kp.npub)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "npub"), "w") as f:
        f.write(kp.npub + "\n")
    enc_path = os.path.join(d, "nsec.enc")
    with open(enc_path, "w") as f:
        f.write(cipher.encrypt_secret(kp.seckey_bytes, password))
    os.chmod(enc_path, 0o600)  # still defence-in-depth, though it's encrypted
    if make_active:
        set_active(kp.npub)
    return d


def load_keypair(npub: str, password: str) -> Keypair:
    with open(os.path.join(identity_dir(npub), "nsec.enc")) as f:
        blob = f.read()
    return Keypair.from_hex(cipher.decrypt_secret(blob, password).hex())


def _prompt_password(npub: str) -> str:
    env = os.environ.get("PIJN_PASSPHRASE")
    if env is not None:
        return env
    return getpass.getpass(f"Passphrase to unlock {npub[:12]}…: ")


def load_active_keypair(npub: str = "") -> Keypair:
    """Load an identity's key for signing (env nsec, else decrypt the file)."""
    nsec = os.environ.get("PIJN_NSEC")
    if nsec:
        return Keypair.from_nsec(nsec.strip())
    npub = npub or active_npub()
    if not npub:
        raise FileNotFoundError("no identity; run `pijn keygen` first")
    if not has_encrypted_key(npub):
        raise FileNotFoundError(f"no encrypted key for {npub} under {pijn_home()}")
    return load_keypair(npub, _prompt_password(npub))
