"""
Minimal site publisher.

Walks a directory, uploads each file to a Blossom server as a blob, builds an
nsite manifest mapping paths -> hashes, signs it, and publishes it to a relay.

This is intentionally minimal: it exists so P1 can meet its exit criterion
(publish a static site and browse it locally). P2 replaces it with a templated
publisher that also handles mutable updates ergonomically. It already exercises
the *real* wire interfaces (Blossom HTTP + relay WebSocket), so what it produces
is readable by any vanilla Nostr/Blossom client.
"""

import mimetypes
import os

from .client.blossom_client import BlossomClient
from .client.relay_client import RelayClient
from .nostr.keys import Keypair
from .nostr.nsite import build_manifest


def _iter_files(directory: str):
    """Yield (absolute_request_path, filesystem_path) for every file."""
    for dirpath, _dirs, files in os.walk(directory):
        for name in files:
            fs_path = os.path.join(dirpath, name)
            rel = os.path.relpath(fs_path, directory)
            request_path = "/" + rel.replace(os.sep, "/")
            yield request_path, fs_path


async def publish_site(directory: str, keypair: Keypair, blossom_url: str,
                       relay_url: str, identifier: str = "", title: str = ""):
    """Publish `directory` as a site. Returns a summary dict."""
    if not os.path.isdir(directory):
        raise NotADirectoryError(directory)

    blossom = BlossomClient(blossom_url)
    paths = {}
    for request_path, fs_path in _iter_files(directory):
        with open(fs_path, "rb") as f:
            data = f.read()
        # Tag the blob with a real content-type so a vanilla Blossom client (or
        # njump in P5) serves it correctly; the gateway re-guesses from the path
        # too, but the stored type is what interop relies on.
        content_type = mimetypes.guess_type(fs_path)[0] or "application/octet-stream"
        descriptor = await blossom.upload(data, keypair, content_type=content_type)
        paths[request_path] = descriptor["sha256"]

    if not paths:
        raise ValueError(f"no files found under {directory}")

    manifest = build_manifest(
        paths=paths, servers=[blossom_url], identifier=identifier, title=title
    ).sign(keypair.seckey_bytes)

    accepted, message = await RelayClient(relay_url).publish(manifest)
    if not accepted:
        raise RuntimeError(f"relay rejected manifest: {message}")

    return {
        "npub": keypair.npub,
        "identifier": identifier,
        "manifest_id": manifest.id,
        "files": len(paths),
        "kind": manifest.kind,
    }
