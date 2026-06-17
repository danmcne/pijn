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
_DEFAULTS = {
    "event_store": {"enabled": True, "listen": "127.0.0.1:4848", "db": "./relay.sqlite"},
    "blob_store": {"enabled": True, "listen": "127.0.0.1:4849", "path": "./blobs"},
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


@dataclass
class Policy:
    nsec_file: str = "./.pijn/nsec"
    npub: str = ""
    services: dict = field(default_factory=dict)
    relays_read: list = field(default_factory=list)
    relays_write: list = field(default_factory=list)
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

    # --- key loading (never from the policy file) ---
    def load_keypair(self) -> Keypair:
        nsec = os.environ.get("PIJN_NSEC")
        if nsec:
            return Keypair.from_nsec(nsec.strip())
        if os.path.exists(self.nsec_file):
            with open(self.nsec_file) as f:
                return Keypair.from_nsec(f.read().strip())
        raise FileNotFoundError(
            f"no key: set PIJN_NSEC or create {self.nsec_file} (try `pijn keygen`)"
        )


def _build_services(raw_services: dict) -> dict:
    services = {}
    for name, defaults in _DEFAULTS.items():
        cfg = {**defaults, **(raw_services.get(name) or {})}
        host, port = _parse_listen(cfg["listen"])
        services[name] = ServiceConfig(
            enabled=bool(cfg.get("enabled", True)),
            host=host, port=port,
            db=cfg.get("db", ""), path=cfg.get("path", ""),
        )
    return services


def load_policy(path: str | None) -> Policy:
    """Load a policy file, or return all-defaults when `path` is None/missing."""
    raw = {}
    if path and os.path.exists(path):
        with open(path) as f:
            raw = yaml.safe_load(f) or {}

    identity = raw.get("identity", {}) or {}
    relays = raw.get("relays", {}) or {}
    blossom = raw.get("blossom", {}) or {}

    return Policy(
        nsec_file=identity.get("nsec_file", "./.pijn/nsec"),
        npub=identity.get("npub", ""),
        services=_build_services(raw.get("services", {}) or {}),
        relays_read=relays.get("read", []),
        relays_write=relays.get("write", []),
        blossom_servers=blossom.get("servers", []),
        raw=raw,
    )
