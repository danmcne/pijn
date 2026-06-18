"""
Transport configuration (P4).

Parsed from the policy `transport:` block (SPEC §4). Two independent concerns:

  * **Outbound** — route the node's own relay (WS) and Blossom (HTTP) client
    connections through Tor's SOCKS proxy, so pulling/publishing can hide the
    node's IP and reach `.onion` peers. Selected by `default: direct|tor` and
    overridable per mirrored site (`sites[].transport`).

  * **Inbound** — expose this node's *own* services as a Tor hidden service via
    the control port. This is the cautious half of P4: `inbound` defaults to
    `off`, and the first safe step is `gateway` — publish ONLY the read-only
    gateway as an `.onion`, never the writable relay/blob ports. `all` (relay +
    blob + gateway) is an explicit opt-in for once an operator trusts the setup.

`socks5h` is used (not `socks5`) so hostnames — including `.onion` — are resolved
by Tor, never leaked to the local resolver.
"""

from dataclasses import dataclass

# Accepted inbound exposure modes, least → most exposed.
INBOUND_OFF = "off"
INBOUND_GATEWAY = "gateway"   # read-only projection only (cautious default-on)
INBOUND_ALL = "all"           # also expose the relay + blob (write surfaces)


@dataclass
class Transport:
    default: str = "direct"            # direct | tor (outbound default)
    socks_host: str = "127.0.0.1"
    socks_port: int = 9050
    control_host: str = "127.0.0.1"
    control_port: int = 9051
    control_password: str = ""
    inbound: str = INBOUND_OFF          # off | gateway | all

    def proxy_url(self, mode: str | None = None) -> str | None:
        """SOCKS proxy URL for the given outbound mode (or the default), or None
        for a direct connection. `socks5h` keeps DNS (and .onion) inside Tor."""
        m = (mode or self.default or "direct").lower()
        if m == "tor":
            return f"socks5h://{self.socks_host}:{self.socks_port}"
        return None

    def proxy_for_url(self, url: str, mode: str | None = None) -> str | None:
        """Like `proxy_url`, but never tunnels a loopback target — you can't (and
        shouldn't) reach your own `127.0.0.1`/`localhost` services over Tor."""
        from urllib.parse import urlsplit
        host = (urlsplit(url).hostname or "").lower()
        if host in ("127.0.0.1", "localhost", "::1") or host.endswith(".localhost"):
            return None
        return self.proxy_url(mode)

    @property
    def inbound_enabled(self) -> bool:
        return self.inbound in (INBOUND_GATEWAY, INBOUND_ALL)

    @property
    def expose_write_services(self) -> bool:
        """True only for `all`: relay + blob are reachable over the onion."""
        return self.inbound == INBOUND_ALL


def _split_hostport(value: str, default_host: str, default_port: int):
    host, _, port = str(value).rpartition(":")
    return (host or default_host), (int(port) if port else default_port)


def parse_transport(raw: dict | None) -> Transport:
    """Build a Transport from the policy `transport:` mapping.

    Back-compat: `inbound_onion: true` (the old boolean) maps to the cautious
    `gateway` mode; `false` maps to `off`. The string forms off/gateway/all are
    preferred.
    """
    t = raw or {}
    tor = t.get("tor") or {}
    socks_host, socks_port = _split_hostport(tor.get("socks", "127.0.0.1:9050"),
                                              "127.0.0.1", 9050)
    ctl_host, ctl_port = _split_hostport(tor.get("control", "127.0.0.1:9051"),
                                         "127.0.0.1", 9051)

    inbound = tor.get("inbound_onion", t.get("inbound_onion", INBOUND_OFF))
    if isinstance(inbound, bool):
        inbound = INBOUND_GATEWAY if inbound else INBOUND_OFF
    inbound = str(inbound).lower()
    if inbound not in (INBOUND_OFF, INBOUND_GATEWAY, INBOUND_ALL):
        inbound = INBOUND_OFF

    return Transport(
        default=str(t.get("default", "direct")).lower(),
        socks_host=socks_host, socks_port=socks_port,
        control_host=ctl_host, control_port=ctl_port,
        control_password=str(tor.get("control_password", "")),
        inbound=inbound,
    )
