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
    def __init__(self, base_url: str, proxy: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.proxy = proxy  # e.g. "socks5h://127.0.0.1:9050" to route over Tor

    async def upload(self, data: bytes, keypair: Keypair, content_type: str = "") -> dict:
        """Upload bytes; return the server's blob descriptor."""
        sha = sha256_hex(data)
        headers = {
            "authorization": _auth_header(keypair, "upload", sha),
            "content-type": content_type or "application/octet-stream",
        }
        async with httpx.AsyncClient(timeout=30, proxy=self.proxy) as client:
            resp = await client.put(f"{self.base_url}/upload", content=data, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def head(self, sha: str) -> int | None:
        """Return the blob's size in bytes via HEAD, or None if unavailable."""
        async with httpx.AsyncClient(timeout=15, proxy=self.proxy) as client:
            try:
                resp = await client.head(f"{self.base_url}/{sha}")
            except httpx.HTTPError:
                return None
        if resp.status_code != 200:
            return None
        cl = resp.headers.get("content-length")
        return int(cl) if cl and cl.isdigit() else None

    async def fetch(self, sha: str, max_bytes: int = 0) -> bytes:
        """Download a blob and verify its bytes hash to `sha`.

        Streams the body and aborts once `max_bytes` is exceeded (0 = no cap),
        so a server that under-reports its size in a HEAD cannot make us buffer
        an unbounded response into memory — the size used for cap/budget
        decisions is advisory; this is the hard backstop.
        """
        async with httpx.AsyncClient(timeout=30, proxy=self.proxy) as client:
            async with client.stream("GET", f"{self.base_url}/{sha}") as resp:
                resp.raise_for_status()
                chunks, total = [], 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if max_bytes and total > max_bytes:
                        raise ValueError(
                            f"blob from {self.base_url} exceeds max size {max_bytes}"
                        )
                    chunks.append(chunk)
        data = b"".join(chunks)
        # Content-addressed integrity: a blob is only trustworthy if its bytes
        # hash to the name we asked for. Without this check, a malicious or
        # buggy Blossom server could serve arbitrary bytes for any hash — the
        # exact failure the "any server is interchangeable" model assumes away.
        if sha256_hex(data) != sha:
            raise ValueError(
                f"blob hash mismatch from {self.base_url}: requested {sha}, "
                f"got {sha256_hex(data)}"
            )
        return data
