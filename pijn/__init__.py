"""
pijn — a self-hostable decentralized web built on Nostr.

This package is the P1 node skeleton: three separable services (event-store
relay, Blossom blob-store, gateway/resolver) plus a YAML policy loader and a
minimal publisher. See SPEC.md for the architecture and roadmap.md for the plan.
"""

__version__ = "0.4.0"  # P4 transport: outbound Tor (SOCKS) + cautious inbound onion (gateway-first)
