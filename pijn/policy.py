"""
Policy loader.

Parses the YAML replication policy defined in SPEC §4 into typed config. P1 uses
the `identity`, `services`, `relays` and `blossom` sections; the rest
(`transport`, `limits`, `eviction`, `moderation`, `sites`) is parsed and kept on
`Policy.raw` for the phases that consume it (P3 replication, P4 transport), so a
full policy file loads cleanly today without those features existing yet.

The secret key is never read from the policy file itself: it comes from
`PIJN_NSEC` in the environment or from the `nsec_file` path, keeping the nsec out
of any document that might be shared.
"""

import os
from dataclasses import dataclass, field

import yaml

from .nostr.keys import Keypair

# Default listen addresses match SPEC §4 (relay 4848 / blob 4849 / gateway 4850).
# db/path are resolved per-identity under ~/.pijn/<npub>/ unless the policy sets them.
_DEFAULTS = {
    "event_store": {"enabled": True, "listen": "127.0.0.1:4848", "db": ""},
    "blob_store": {"enabled": True, "listen": "127.0.0.1:4849", "path": ""},
    "gateway": {"enabled": True, "listen": "127.0.0.1:4850"},
}


@dataclass
class ServiceConfig:
    enabled: bool
    host: str
    port: int
    db: str = ""
    path: str = ""

    @property
    def listen(self) -> str:
        return f"{self.host}:{self.port}"


def _parse_listen(value: str) -> tuple[str, int]:
    host, _, port = value.rpartition(":")
    return host or "127.0.0.1", int(port)


_SIZE_UNITS = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}


def parse_size(value) -> int:
    """Parse a human size like '100MB' / '20GB' into bytes. Bare ints pass through."""
    s = str(value).strip().upper()
    for unit in ("KB", "MB", "GB", "TB", "B"):  # multi-char first
        if s.endswith(unit):
            return int(float(s[: -len(unit)]) * _SIZE_UNITS[unit])
    return int(s)


_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(value) -> int:
    """Parse '15m' / '1h' / '2d' into seconds. Bare ints pass through as seconds."""
    s = str(value).strip().lower()
    if s and s[-1] in _DURATION_UNITS:
        return int(float(s[:-1]) * _DURATION_UNITS[s[-1]])
    return int(s)


@dataclass
class SiteConfig:
    """One entry under `sites:` — a site this node chooses to host (SPEC §4)."""
    name: str
    pubkey: str            # hex (normalized from npub or hex in the policy)
    identifier: str = ""   # "" = root site; else named
    seed: bool = True      # advertise/serve to others (announcement deferred; see replication.py)
    pin: bool = True       # never evicted; ignores caps
    storage_cap: int = 0   # bytes; 0 = unlimited (file-level partial seed if exceeded)
    transport: str = "direct"
    refresh: int = 900     # seconds between manifest re-pulls


@dataclass
class Policy:
    nsec_file: str = "./.pijn/nsec"
    npub: str = ""
    data_dir: str = "."
    services: dict = field(default_factory=dict)
    relays_read: list = field(default_factory=list)
    relays_write: list = field(default_factory=list)
    relays_trusted: list = field(default_factory=list)
    blossom_servers: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    # --- service accessors ---
    @property
    def event_store(self) -> ServiceConfig:
        return self.services["event_store"]

    @property
    def blob_store(self) -> ServiceConfig:
        return self.services["blob_store"]

    @property
    def gateway(self) -> ServiceConfig:
        return self.services["gateway"]

    @property
    def blossom_public_url(self) -> str:
        """The URL other parties use to fetch this node's blobs."""
        bs = self.blob_store
        return f"http://{bs.host}:{bs.port}"

    @property
    def relay_public_url(self) -> str:
        es = self.event_store
        return f"ws://{es.host}:{es.port}"

    @property
    def blob_max_size(self) -> int:
        """Max accepted blob size in bytes (limits.blob_max_size; default 100MB)."""
        raw = (self.raw.get("limits") or {}).get("blob_max_size", "100MB")
        return parse_size(raw)

    @property
    def storage_total(self) -> int:
        """Node-wide storage ceiling in bytes (limits.storage_total; 0 = unlimited)."""
        raw = (self.raw.get("limits") or {}).get("storage_total")
        return parse_size(raw) if raw else 0

    @property
    def bandwidth_day(self) -> int:
        raw = (self.raw.get("limits") or {}).get("bandwidth_day")
        return parse_size(raw) if raw else 0

    @property
    def bandwidth_month(self) -> int:
        raw = (self.raw.get("limits") or {}).get("bandwidth_month")
        return parse_size(raw) if raw else 0

    @property
    def state_dir(self) -> str:
        """Where small persisted state (e.g. the bandwidth meter) lives."""
        return self.data_dir

    @property
    def eviction(self) -> dict:
        """Eviction config (default 'manual' — never auto-evict; SPEC §4)."""
        e = self.raw.get("eviction") or {}
        return {"policy": e.get("policy", "manual"),
                "protect_pinned": bool(e.get("protect_pinned", True))}

    @property
    def allow_private_sources(self) -> bool:
        """If True, the replication SSRF guard is relaxed so network-discovered
        blob servers/relays on private/loopback addresses are allowed (local
        testing only). Default False — network-supplied private targets are
        refused. (`replication.allow_private_sources`)"""
        return bool((self.raw.get("replication") or {}).get("allow_private_sources", False))

    @property
    def transport(self):
        """Parsed `transport:` config (outbound Tor + inbound onion; P4)."""
        from .transport.config import parse_transport
        return parse_transport(self.raw.get("transport"))

    @property
    def sites(self) -> list:
        """Parsed `sites:` entries (the replication controller's work list)."""
        from .nostr.bech32 import normalize_pubkey

        out = []
        for entry in (self.raw.get("sites") or []):
            pk = entry.get("pubkey", "")
            try:
                pk = normalize_pubkey(pk)
            except ValueError:
                continue  # skip entries without a usable key
            out.append(SiteConfig(
                name=entry.get("name", pk[:8]),
                pubkey=pk,
                identifier=entry.get("identifier", "") or "",
                seed=bool(entry.get("seed", True)),
                pin=bool(entry.get("pin", True)),
                storage_cap=parse_size(entry["storage_cap"]) if entry.get("storage_cap") else 0,
                transport=entry.get("transport", "direct"),
                refresh=parse_duration(entry.get("refresh", 900)),
            ))
        return out

    # --- key loading (never from the policy file; nsec is encrypted at rest) ---
    def load_keypair(self) -> Keypair:
        from . import keystore
        return keystore.load_active_keypair(self.npub)


def _build_services(raw_services: dict, data_dir: str) -> dict:
    services = {}
    for name, defaults in _DEFAULTS.items():
        cfg = {**defaults, **(raw_services.get(name) or {})}
        host, port = _parse_listen(cfg["listen"])
        db = cfg.get("db") or os.path.join(data_dir, "relay.sqlite")
        path = cfg.get("path") or os.path.join(data_dir, "blobs")
        services[name] = ServiceConfig(
            enabled=bool(cfg.get("enabled", True)),
            host=host, port=port, db=db, path=path,
        )
    return services


def load_policy(path: str | None) -> Policy:
    """Load a policy file, or return all-defaults when `path` is None/missing."""
    from . import keystore

    raw = {}
    if path and os.path.exists(path):
        with open(path) as f:
            raw = yaml.safe_load(f) or {}

    identity = raw.get("identity", {}) or {}
    relays = raw.get("relays", {}) or {}
    blossom = raw.get("blossom", {}) or {}

    # The node's identity (operator) and its data home under ~/.pijn/<npub>/.
    npub = identity.get("npub") or keystore.active_npub()
    data_dir = keystore.identity_dir(npub) if npub else "."

    return Policy(
        nsec_file=identity.get("nsec_file", "./.pijn/nsec"),
        npub=npub,
        data_dir=data_dir,
        services=_build_services(raw.get("services", {}) or {}, data_dir),
        relays_read=relays.get("read", []),
        relays_write=relays.get("write", []),
        relays_trusted=relays.get("trusted", []),
        blossom_servers=blossom.get("servers", []),
        raw=raw,
    )
