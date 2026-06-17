"""
Replication controller (P3) — the fifth, state-less coordinator.

For each site in policy `sites:`, it pulls the site's manifest (and, for a blog,
its kind-30023 posts) from source relays and the manifest's blobs from Blossom
servers, writing them into *this node's own* event-store and blob-store. After a
sync, this node's gateway serves the site from local storage — so the site stays
reachable when its author goes offline (the P3 exit). The controller owns no
storage of its own; it only drives the two stores.

Trust: everything pulled is verified before it is stored — event signatures via
`Event.verify()`, blob bytes via the content-address check in `BlossomClient`.
A source relay or Blossom server can therefore be untrusted; it cannot inject
content under someone else's key or serve wrong bytes for a hash.

Caps (SPEC §4): `pin` bypasses all caps. Otherwise a per-site `storage_cap`
triggers *file-level partial seeding* — files are taken in manifest order until
the cap is reached and the rest skipped — and a node-wide `storage_total` is a
hard ceiling. Active LRU/popularity eviction, bandwidth budgets, and seeder
discovery are hooks left for 0.3.1; `seed` is recorded but, until announcement
exists, only governs advertisement, not blob serving (a content-addressed store
serves any blob by hash, and blobs are shared across sites).
"""

import asyncio

from .client.blossom_client import BlossomClient
from .client.relay_client import RelayClient
from .nostr.nsite import (
    KIND_LEGACY,
    KIND_LONGFORM,
    KIND_NAMED,
    KIND_ROOT,
    parse_manifest,
)


class ReplicationController:
    def __init__(self, store, blob_store, sites, source_relays,
                 default_blossom, storage_total=0):
        self.store = store                      # local EventStore (write target)
        self.blob_store = blob_store            # local BlobStore (write target)
        self.sites = sites                      # list[SiteConfig]
        self.source_relays = list(source_relays)
        self.default_blossom = list(default_blossom)
        self.storage_total = storage_total
        self._node_bytes = blob_store.total_bytes() if blob_store else 0

    # --- relay/blob helpers --------------------------------------------------

    async def _pull_newest(self, filters):
        """Query every source relay; return the newest valid, matching event."""
        newest = None
        for url in self.source_relays:
            try:
                events = await RelayClient(url).query(filters)
            except Exception:
                continue
            for ev in events:
                if ev.verify() and (newest is None or ev.created_at > newest.created_at):
                    newest = ev
        return newest

    async def _pull_all(self, filters):
        seen, out = set(), []
        for url in self.source_relays:
            try:
                events = await RelayClient(url).query(filters)
            except Exception:
                continue
            for ev in events:
                if ev.id not in seen and ev.verify():
                    seen.add(ev.id)
                    out.append(ev)
        return out

    async def _blob_size(self, sha, sources):
        for url in sources:
            size = await BlossomClient(url).head(sha)
            if size is not None:
                return size
        return None

    async def _fetch_blob(self, sha, sources):
        for url in sources:
            try:
                return await BlossomClient(url).fetch(sha)  # hash-verified inside
            except Exception:
                continue
        return None

    # --- sync ----------------------------------------------------------------

    async def sync_site(self, site) -> dict:
        report = {"name": site.name, "pubkey": site.pubkey[:12],
                  "identifier": site.identifier, "manifest": None,
                  "files_fetched": 0, "files_present": 0, "files_skipped": 0,
                  "posts": 0, "bytes": 0, "missing": []}

        if site.identifier:
            mf = [{"authors": [site.pubkey], "kinds": [KIND_NAMED],
                   "#d": [site.identifier], "limit": 1}]
        else:
            mf = [{"authors": [site.pubkey], "kinds": [KIND_ROOT, KIND_LEGACY], "limit": 1}]
        manifest_event = await self._pull_newest(mf)
        if manifest_event is None or manifest_event.pubkey != site.pubkey:
            report["manifest"] = "not found"
            return report

        self.store.store(manifest_event)            # already verified in _pull_newest
        report["manifest"] = manifest_event.id
        manifest = parse_manifest(manifest_event)
        sources = list(dict.fromkeys((manifest.get("servers") or []) + self.default_blossom))

        # A blog's content is in events, not blobs: mirror the posts too.
        if manifest.get("app") == "blog":
            for post in await self._pull_all([{"authors": [site.pubkey],
                                               "kinds": [KIND_LONGFORM]}]):
                self.store.store(post)
                report["posts"] += 1

        for sha in manifest.get("paths", {}).values():
            if self.blob_store.has(sha):
                report["files_present"] += 1
                continue
            size = await self._blob_size(sha, sources)
            if not site.pin and self.storage_total and size and \
                    self._node_bytes + size > self.storage_total:
                report["files_skipped"] += 1
                continue  # node ceiling reached
            if not site.pin and site.storage_cap and size and \
                    report["bytes"] + size > site.storage_cap:
                report["files_skipped"] += 1
                continue  # per-site cap: partial seed, keep trying smaller files
            data = await self._fetch_blob(sha, sources)
            if data is None:
                report["missing"].append(sha[:12])
                continue
            self.blob_store.put(data, pubkey=site.pubkey)
            report["files_fetched"] += 1
            report["bytes"] += len(data)
            self._node_bytes += len(data)

        return report

    async def sync_all(self) -> list:
        self._node_bytes = self.blob_store.total_bytes()
        reports = []
        for site in self.sites:
            reports.append(await self.sync_site(site))
        return reports

    async def run_forever(self):
        """Sync on startup, then re-sync each site on its own `refresh` cadence."""
        if not self.sites:
            return
        await self.sync_all()
        # Re-sync on the shortest configured cadence; cheap because unchanged
        # manifests and already-present blobs are skipped.
        interval = min((s.refresh for s in self.sites), default=900)
        while True:
            await asyncio.sleep(max(interval, 5))
            try:
                await self.sync_all()
            except Exception:
                pass  # transient relay/blob errors: try again next cycle
