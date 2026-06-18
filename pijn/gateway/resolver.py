"""
Site resolver.

Turns (pubkey, identifier, request_path) into bytes + content-type by:
  1. fetching the site manifest event (nsite, NIP-5A),
  2. mapping the request path to a blob hash,
  3. fetching that blob.

Both steps go through small pluggable *sources* so the resolver works two ways
without changing its logic (SPEC §2):

  * co-resident in the daemon  -> Local sources read the shared SQLite DB and
    blob directory directly (fast, deterministic, no network).
  * standalone gateway         -> Remote sources query relays (WebSocket) and
    Blossom servers (HTTP).

The resolver itself owns no state — it is a pure projection of events + blobs.
"""

import mimetypes

from . import blog as blog_render
from ..nostr.nsite import (
    KIND_LEGACY,
    KIND_LONGFORM,
    KIND_NAMED,
    KIND_ROOT,
    normalize_request_path,
    parse_manifest,
    resolve_blob,
)


# --- event sources -----------------------------------------------------------

class LocalEventSource:
    """Read manifests straight from a co-resident EventStore."""

    def __init__(self, store):
        self.store = store

    def get_manifest(self, pubkey: str, identifier: str = ""):
        if identifier:
            filters = [{"authors": [pubkey], "kinds": [KIND_NAMED],
                        "#d": [identifier], "limit": 1}]
        else:
            filters = [{"authors": [pubkey], "kinds": [KIND_ROOT, KIND_LEGACY], "limit": 1}]
        events = self.store.query(filters)
        return events[0] if events else None

    def get_posts(self, pubkey: str):
        """All of a pubkey's kind-30023 long-form posts (newest first)."""
        return self.store.query([{"authors": [pubkey], "kinds": [KIND_LONGFORM]}])


class RelayEventSource:
    """Read manifests from one or more remote relays (WebSocket)."""

    def __init__(self, relay_urls: list, proxy: str | None = None):
        self.relay_urls = relay_urls
        self.proxy = proxy

    async def get_manifest(self, pubkey: str, identifier: str = ""):
        from ..client.relay_client import RelayClient
        if identifier:
            filters = [{"authors": [pubkey], "kinds": [KIND_NAMED],
                        "#d": [identifier], "limit": 1}]
        else:
            filters = [{"authors": [pubkey], "kinds": [KIND_ROOT, KIND_LEGACY], "limit": 1}]
        newest = None
        for url in self.relay_urls:
            try:
                for ev in await RelayClient(url, proxy=self.proxy).query(filters):
                    if newest is None or ev.created_at > newest.created_at:
                        newest = ev
            except Exception:
                continue
        return newest

    async def get_posts(self, pubkey: str):
        from ..client.relay_client import RelayClient
        filters = [{"authors": [pubkey], "kinds": [KIND_LONGFORM]}]
        seen, posts = set(), []
        for url in self.relay_urls:
            try:
                for ev in await RelayClient(url, proxy=self.proxy).query(filters):
                    if ev.id not in seen:
                        seen.add(ev.id)
                        posts.append(ev)
            except Exception:
                continue
        return posts


# --- blob sources ------------------------------------------------------------

class LocalBlobSource:
    def __init__(self, blob_store):
        self.blob_store = blob_store

    def get(self, sha: str, server_hints=None):
        return self.blob_store.get(sha)


class HttpBlobSource:
    def __init__(self, default_servers: list, proxy: str | None = None):
        self.default_servers = default_servers
        self.proxy = proxy

    async def get(self, sha: str, server_hints=None):
        from ..client.blossom_client import BlossomClient
        for url in list(server_hints or []) + self.default_servers:
            try:
                return await BlossomClient(url, proxy=self.proxy).fetch(sha)
            except Exception:
                continue
        return None


# --- resolver ----------------------------------------------------------------

class Resolver:
    """Compose an event source + a blob source into site resolution.

    `is_async` controls whether the sources are awaited (remote) or called
    directly (local), so a single resolve() body serves both deployments.
    """

    def __init__(self, event_source, blob_source, is_async: bool = False):
        self.event_source = event_source
        self.blob_source = blob_source
        self.is_async = is_async

    async def resolve(self, pubkey: str, request_path: str, identifier: str = ""):
        """Resolve a request to `(bytes, content_type, generated)` or None.

        `generated` is True when the bytes are HTML pijn rendered itself (a blog
        projection) and False when they are a raw, author-supplied blob — the
        gateway uses it to decide how strict a Content-Security-Policy to apply.
        """
        if self.is_async:
            event = await self.event_source.get_manifest(pubkey, identifier)
        else:
            event = self.event_source.get_manifest(pubkey, identifier)
        if event is None:
            return None

        manifest = parse_manifest(event)

        if manifest.get("app") == "blog":
            return await self._resolve_blog(pubkey, request_path, manifest)

        sha = resolve_blob(manifest, request_path)
        if sha is None:
            return None

        if self.is_async:
            data = await self.blob_source.get(sha, manifest["servers"])
        else:
            data = self.blob_source.get(sha, manifest["servers"])
        if data is None:
            return None

        content_type, _ = mimetypes.guess_type(normalize_request_path(request_path))
        return data, content_type or "application/octet-stream", False

    async def _resolve_blog(self, pubkey: str, request_path: str, manifest: dict):
        """Project the pubkey's kind-30023 posts into an index + post pages."""
        if self.is_async:
            posts = await self.event_source.get_posts(pubkey)
        else:
            posts = self.event_source.get_posts(pubkey)

        path = request_path.split("?", 1)[0].strip("/")
        if path in ("", "index.html"):
            return blog_render.render_index(manifest, pubkey, posts), "text/html; charset=utf-8", True

        # Otherwise the path is a post slug (the post's `d` tag).
        for post in posts:
            if post.d_tag == path:
                return blog_render.render_post(manifest, pubkey, post), "text/html; charset=utf-8", True
        return None
