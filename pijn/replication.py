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

from . import eviction as eviction_strategy
from .client.blossom_client import BlossomClient
from .client.relay_client import RelayClient
from .discovery import discover_relays, discover_seeders, site_coord
from .netguard import filter_safe
from .nostr.nsite import (
    KIND_LEGACY,
    KIND_LONGFORM,
    KIND_NAMED,
    KIND_ROOT,
    parse_manifest,
)


class ReplicationController:
    def __init__(self, store, blob_store, sites, source_relays,
                 default_blossom, storage_total=0, eviction=None, meter=None,
                 blob_max_size=0, allow_private=False, transport=None):
        self.store = store                      # local EventStore (write target)
        self.blob_store = blob_store            # local BlobStore (write target)
        self.sites = sites                      # list[SiteConfig]
        self.source_relays = list(source_relays)
        self.default_blossom = list(default_blossom)
        self.storage_total = storage_total
        self.eviction = eviction or {"policy": "manual", "protect_pinned": True}
        self.meter = meter                      # BandwidthMeter or None (unlimited)
        self.blob_max_size = blob_max_size      # hard per-blob download ceiling (0 = none)
        self.allow_private = allow_private      # relax the SSRF guard (local testing)
        if transport is None:
            from .transport.config import Transport
            transport = Transport()
        self.transport = transport              # outbound Tor selection (per site)
        self._node_bytes = blob_store.total_bytes() if blob_store else 0

    # --- relay/blob helpers --------------------------------------------------

    async def _pull_newest(self, filters, relays, proxy=None):
        """Query every relay; return the newest valid, matching event."""
        newest = None
        for url in relays:
            try:
                events = await RelayClient(url, proxy=proxy).query(filters)
            except Exception:
                continue
            for ev in events:
                if ev.verify() and (newest is None or ev.created_at > newest.created_at):
                    newest = ev
        return newest

    async def _pull_all(self, filters, relays, proxy=None):
        seen, out = set(), []
        for url in relays:
            try:
                events = await RelayClient(url, proxy=proxy).query(filters)
            except Exception:
                continue
            for ev in events:
                if ev.id not in seen and ev.verify():
                    seen.add(ev.id)
                    out.append(ev)
        return out

    async def _blob_size(self, sha, sources, proxy=None):
        for url in sources:
            size = await BlossomClient(url, proxy=proxy).head(sha)
            if size is not None:
                return size
        return None

    async def _fetch_blob(self, sha, sources, proxy=None):
        for url in sources:
            try:
                # max_bytes is the hard backstop against a server that
                # under-reports its size in HEAD (see BlossomClient.fetch).
                return await BlossomClient(url, proxy=proxy).fetch(sha, max_bytes=self.blob_max_size)
            except Exception:
                continue
        return None

    # --- sync ----------------------------------------------------------------

    async def sync_site(self, site) -> dict:
        report = {"name": site.name, "pubkey": site.pubkey[:12],
                  "identifier": site.identifier, "manifest": None,
                  "files_fetched": 0, "files_present": 0, "files_skipped": 0,
                  "posts": 0, "bytes": 0, "missing": [],
                  "relays_discovered": 0, "seeders": 0}

        # Per-site transport: route this site's pulls over Tor when the site (or
        # the node default) selects it. `proxy` is None for a direct connection.
        proxy = self.transport.proxy_url(getattr(site, "transport", None))

        # NIP-65 discovery: where does this author publish? Add their outbox
        # relays to whatever the operator configured. Discovered relays are
        # network-supplied, so they pass through the SSRF guard; the operator's
        # own `source_relays` are trusted and exempt.
        discovered = await discover_relays(site.pubkey, self.source_relays, want="write", proxy=proxy)
        discovered = filter_safe(discovered, self.allow_private)
        report["relays_discovered"] = len(discovered)
        relays = list(dict.fromkeys(self.source_relays + discovered))

        # Seeder discovery: other nodes advertising they host this site, found on
        # the relays we already know. Their relays/servers are extra places to
        # pull the manifest and blobs from — resilience when the author is gone.
        site_kind = KIND_NAMED if site.identifier else KIND_ROOT
        coord = site_coord(site_kind, site.pubkey, site.identifier)
        seeders = await discover_seeders(coord, relays, proxy=proxy)
        report["seeders"] = len(seeders)
        seeder_servers, seeder_relays = [], []
        for s in seeders:
            seeder_servers += s["servers"]
            seeder_relays += s["relays"]
        # All seeder-supplied URLs are untrusted network input → guard them.
        seeder_servers = filter_safe(seeder_servers, self.allow_private)
        seeder_relays = filter_safe(seeder_relays, self.allow_private)
        relays = list(dict.fromkeys(relays + seeder_relays))

        if site.identifier:
            mf = [{"authors": [site.pubkey], "kinds": [KIND_NAMED],
                   "#d": [site.identifier], "limit": 1}]
        else:
            mf = [{"authors": [site.pubkey], "kinds": [KIND_ROOT, KIND_LEGACY], "limit": 1}]
        manifest_event = await self._pull_newest(mf, relays, proxy=proxy)
        if manifest_event is None or manifest_event.pubkey != site.pubkey:
            report["manifest"] = "not found"
            return report

        self.store.store(manifest_event)            # already verified in _pull_newest
        report["manifest"] = manifest_event.id
        manifest = parse_manifest(manifest_event)
        # Manifest `server` hints are author/network-supplied → guard them; the
        # operator's own `default_blossom` is trusted and appended unfiltered.
        manifest_servers = filter_safe(manifest.get("servers") or [], self.allow_private)
        sources = list(dict.fromkeys(
            manifest_servers + seeder_servers + self.default_blossom))

        # A blog's content is in events, not blobs: mirror the posts too.
        if manifest.get("app") == "blog":
            for post in await self._pull_all([{"authors": [site.pubkey],
                                               "kinds": [KIND_LONGFORM]}], relays, proxy=proxy):
                self.store.store(post)
                report["posts"] += 1

        for sha in manifest.get("paths", {}).values():
            if self.blob_store.has(sha):
                report["files_present"] += 1
                continue
            size = await self._blob_size(sha, sources, proxy=proxy)
            if not site.pin and self.storage_total and size and \
                    self._node_bytes + size > self.storage_total:
                report["files_skipped"] += 1
                continue  # node ceiling reached
            if not site.pin and site.storage_cap and size and \
                    report["bytes"] + size > site.storage_cap:
                report["files_skipped"] += 1
                continue  # per-site cap: partial seed, keep trying smaller files
            if self.meter is not None and size and not self.meter.allow(size):
                report["files_skipped"] += 1
                continue  # bandwidth budget reached (applies even to pinned sites)
            data = await self._fetch_blob(sha, sources, proxy=proxy)
            if data is None:
                report["missing"].append(sha[:12])
                continue
            self.blob_store.put(data, pubkey=site.pubkey)
            if self.meter is not None:
                self.meter.record(len(data))
            report["files_fetched"] += 1
            report["bytes"] += len(data)
            self._node_bytes += len(data)

        return report

    def _protected_shas(self) -> set:
        """Blob hashes of pinned sites — never evicted when protect_pinned is on."""
        shas = set()
        if not self.eviction.get("protect_pinned", True):
            return shas
        for site in self.sites:
            if not site.pin:
                continue
            if site.identifier:
                rows = self.store.query([{"authors": [site.pubkey], "kinds": [KIND_NAMED],
                                          "#d": [site.identifier], "limit": 1}])
            else:
                rows = self.store.query([{"authors": [site.pubkey],
                                          "kinds": [KIND_ROOT, KIND_LEGACY], "limit": 1}])
            if rows:
                shas.update(parse_manifest(rows[0]).get("paths", {}).values())
        return shas

    def _enforce_ceiling(self):
        """Make room under storage_total using the configured eviction strategy."""
        policy = self.eviction.get("policy", "manual")
        if policy == "manual" or not self.storage_total:
            return 0
        total = self.blob_store.total_bytes()
        if total <= self.storage_total:
            return 0
        victims = eviction_strategy.select_evictions(
            self.blob_store.entries(), total - self.storage_total,
            policy=policy, protected=self._protected_shas())
        for sha in victims:
            self.blob_store.evict(sha)
        return len(victims)

    async def sync_all(self) -> list:
        self._enforce_ceiling()
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
