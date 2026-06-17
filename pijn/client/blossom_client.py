"""
Blossom HTTP client.

Used by the publisher to push blobs and (later, P3) by the replication
controller to mirror them. Builds the kind-24242 authorization token locally —
signing happens here, on the host, never server-side.
"""

import base64
import json
import time

import httpx

from ..nostr.event import make_event
from ..nostr.keys import Keypair
from ..blob_store.storage import sha256_hex


def _auth_header(keypair: Keypair, verb: str, sha: str, ttl: int = 300) -> str:
    """Create a base64 `Authorization: Nostr ...` value for one blob action."""
    event = make_event(
        kind=24242,
        content=f"{verb} {sha}",
        tags=[["t", verb], ["x", sha], ["expiration", str(int(time.time()) + ttl)]],
    ).sign(keypair.seckey_bytes)
    token = base64.b64encode(json.dumps(event.to_dict()).encode()).decode()
    return f"Nostr {token}"


class BlossomClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def upload(self, data: bytes, keypair: Keypair, content_type: str = "") -> dict:
        """Upload bytes; return the server's blob descriptor."""
        sha = sha256_hex(data)
        headers = {
            "authorization": _auth_header(keypair, "upload", sha),
            "content-type": content_type or "application/octet-stream",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.put(f"{self.base_url}/upload", content=data, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def fetch(self, sha: str) -> bytes:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{self.base_url}/{sha}")
            resp.raise_for_status()
            return resp.content
