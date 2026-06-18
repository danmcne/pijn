"""
Blog authoring (P2).

`publish_post` turns a Markdown file into a kind-30023 long-form event and sends
it to a relay — a standard NIP-23 article that any long-form Nostr client can
read. `publish_blog` publishes the small nsite manifest (tagged `app=blog`) that
marks an origin as a blog so the gateway projects the author's posts there.

Re-running either is the update path: a post re-uses its slug (the `d` tag) and
the relay supersedes the previous version; the blog manifest is replaceable too.
"""

import os
import re
import time

from .client.relay_client import RelayClient
from .nostr.event import make_event
from .nostr.keys import Keypair
from .nostr.nsite import KIND_LONGFORM, build_manifest

_H1 = re.compile(r"^#\s+(.*)$", re.M)


def _slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    return re.sub(r"[\s_]+", "-", text) or "post"


async def publish_post(path: str, keypair: Keypair, relay_url: str, slug: str = "",
                       title: str = "", summary: str = "", tags=(), proxy: str | None = None):
    """Publish a Markdown file as a kind-30023 long-form post. Returns a summary."""
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    with open(path, encoding="utf-8") as f:
        body = f.read()

    if not title:
        m = _H1.search(body)
        title = m.group(1).strip() if m else os.path.splitext(os.path.basename(path))[0]
    slug = slug or _slugify(os.path.splitext(os.path.basename(path))[0])

    event_tags = [["d", slug], ["title", title], ["published_at", str(int(time.time()))]]
    if summary:
        event_tags.append(["summary", summary])
    for t in tags:
        event_tags.append(["t", t])

    event = make_event(KIND_LONGFORM, content=body, tags=event_tags).sign(keypair.seckey_bytes)
    accepted, message = await RelayClient(relay_url, proxy=proxy).publish(event)
    if not accepted:
        raise RuntimeError(f"relay rejected post: {message}")
    return {"npub": keypair.npub, "slug": slug, "title": title, "id": event.id}


async def publish_blog(keypair: Keypair, relay_url: str, title: str = "",
                       description: str = "", identifier: str = "", proxy: str | None = None):
    """Publish/update the manifest that marks an origin as a blog."""
    manifest = build_manifest(
        paths={}, servers=[], identifier=identifier,
        title=title, description=description, app="blog",
    ).sign(keypair.seckey_bytes)
    accepted, message = await RelayClient(relay_url, proxy=proxy).publish(manifest)
    if not accepted:
        raise RuntimeError(f"relay rejected blog manifest: {message}")
    return {"npub": keypair.npub, "identifier": identifier,
            "manifest_id": manifest.id, "kind": manifest.kind}
