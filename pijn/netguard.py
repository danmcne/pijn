"""
SSRF guard for network-supplied URLs.

The replication controller pulls from blob servers and relays whose URLs come
from *untrusted* network data — a site manifest's `server` hints and kind-30888
seeder announcements. Without a check, a malicious manifest/seeder could make
this node issue requests to internal addresses (`127.0.0.1`, RFC-1918,
`169.254.169.254`, …): a classic server-side request forgery surface that gets
sharper once P4 makes nodes reachable and once they run in cloud/datacenter
networks.

`is_safe_public_url` resolves a URL's host and rejects it if *any* resolved
address is loopback, private, link-local, reserved, multicast, or unspecified.
Operator-configured endpoints (your own `relays.read` / `blossom.servers`) are
trusted and are *not* passed through this guard; only network-discovered URLs
are. Set `allow_private=True` (policy `replication.allow_private_sources`) to
relax it for local testing.

`.onion` hosts pass: they are not internal-network targets and are reached over
Tor's SOCKS proxy (P4), never resolved against the local network.
"""

import ipaddress
import socket
from urllib.parse import urlsplit

_ALLOWED_SCHEMES = ("http", "https", "ws", "wss")


def _host_port(url: str):
    parts = urlsplit(url)
    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        return None, None, None
    return parts.scheme.lower(), parts.hostname, parts.port


def _addr_is_public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (
        addr.is_loopback or addr.is_private or addr.is_link_local
        or addr.is_multicast or addr.is_reserved or addr.is_unspecified
    )


def is_safe_public_url(url: str, allow_private: bool = False) -> bool:
    """True iff `url` is well-formed and every address its host resolves to is
    a routable public address (or `allow_private`/`.onion` exempts it)."""
    scheme, host, _ = _host_port(url)
    if not scheme or not host:
        return False
    if allow_private:
        return True
    host = host.strip("[]")  # IPv6 literal brackets
    if host.endswith(".onion"):
        return True  # routed via Tor; not a local-network target

    # Literal IP: check directly (don't let DNS be skipped).
    try:
        ipaddress.ip_address(host)
        return _addr_is_public(host)
    except ValueError:
        pass

    # Hostname: every resolved address must be public (guards DNS-rebinding to
    # a private IP for at least the names that resolve to one at check time).
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    if not infos:
        return False
    return all(_addr_is_public(info[4][0]) for info in infos)


def filter_safe(urls, allow_private: bool = False) -> list:
    """Keep only the URLs that pass `is_safe_public_url`, order preserved."""
    return [u for u in urls if is_safe_public_url(u, allow_private)]
