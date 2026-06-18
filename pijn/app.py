"""
Service composition + the daemon runner.

`build_node` constructs whichever services the policy enables and wires the
gateway resolver to local or remote sources:

  * event-store and blob-store both enabled  -> gateway reads them in-process
    (Local sources: shared SQLite + blob dir).
  * otherwise                                 -> gateway resolves over the wire
    (Remote sources: relays + Blossom servers from the policy).

`run` then serves every enabled app on its own port (SPEC §2: separable
services), so the default install runs them together while any one can run
alone via `--only`.
"""

import asyncio

import uvicorn

from .blob_store import BlobStore, build_blob_app
from .event_store import EventStore, build_relay_app
from .gateway import (
    HttpBlobSource,
    LocalBlobSource,
    LocalEventSource,
    RelayEventSource,
    Resolver,
    build_gateway_app,
)
from .policy import Policy


class Node:
    """Holds the constructed stores and the per-service (app, host, port)."""

    def __init__(self):
        self.store = None
        self.blob_store = None
        self.apps = {}  # name -> (app, host, port)


def build_node(policy: Policy, only: str | None = None) -> Node:
    node = Node()
    es, bs, gw = policy.event_store, policy.blob_store, policy.gateway
    import os
    os.makedirs(policy.data_dir, exist_ok=True)  # ~/.pijn/<npub>/

    def wanted(name: str, enabled: bool) -> bool:
        return enabled and (only is None or only == name)

    if wanted("event_store", es.enabled):
        node.store = EventStore(es.db)
        node.apps["event_store"] = (build_relay_app(node.store, policy), es.host, es.port)

    if wanted("blob_store", bs.enabled):
        node.blob_store = BlobStore(bs.path)
        from .moderation import Moderation
        node.apps["blob_store"] = (
            build_blob_app(node.blob_store, policy.blossom_public_url,
                           max_size=policy.blob_max_size,
                           moderation=Moderation.from_policy(policy)),
            bs.host, bs.port,
        )

    if wanted("gateway", gw.enabled):
        # If we have both local stores in-process, resolve locally; else remote.
        if node.store is not None and node.blob_store is not None:
            resolver = Resolver(
                LocalEventSource(node.store), LocalBlobSource(node.blob_store), is_async=False,
            )
        else:
            _proxy = policy.transport.proxy_url()
            resolver = Resolver(
                RelayEventSource(policy.relays_read or [policy.relay_public_url], proxy=_proxy),
                HttpBlobSource(policy.blossom_servers or [policy.blossom_public_url], proxy=_proxy),
                is_async=True,
            )
        node.apps["gateway"] = (build_gateway_app(resolver), gw.host, gw.port)

    return node


async def _serve_all(node: Node, controller=None):
    servers = [
        uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info"))
        for (app, host, port) in node.apps.values()
    ]
    tasks = [s.serve() for s in servers]
    if controller is not None:
        tasks.append(controller.run_forever())
    await asyncio.gather(*tasks)


def build_controller(policy: Policy, node: Node):
    """A replication controller iff this node has local stores to mirror into."""
    if node.store is None or node.blob_store is None or not policy.sites:
        return None
    import os

    from .bandwidth import BandwidthMeter
    from .replication import ReplicationController

    meter = BandwidthMeter(
        os.path.join(policy.state_dir, "bandwidth.json"),
        day_cap=policy.bandwidth_day, month_cap=policy.bandwidth_month,
    )
    return ReplicationController(
        store=node.store, blob_store=node.blob_store, sites=policy.sites,
        source_relays=policy.relays_read or [policy.relay_public_url],
        default_blossom=policy.blossom_servers or [policy.blossom_public_url],
        storage_total=policy.storage_total, eviction=policy.eviction, meter=meter,
        blob_max_size=policy.blob_max_size, allow_private=policy.allow_private_sources,
        transport=policy.transport,
    )


def _start_onion(policy: Policy, node: "Node"):
    """If inbound onion is enabled, publish the node's services as a hidden
    service and return the live OnionService (kept open to hold the onion).

    Cautious by default: only the read-only gateway is exposed unless the policy
    explicitly sets `transport.tor.inbound_onion: all`, which also exposes the
    writable relay and blob ports.
    """
    t = policy.transport
    if not t.inbound_enabled:
        return None
    from .transport import OnionService, reachable

    if not reachable(t.control_host, t.control_port):
        print(f"pijn: inbound onion requested but Tor control port "
              f"{t.control_host}:{t.control_port} is unreachable — skipping. "
              f"Is Tor running with an open ControlPort?")
        return None

    # Map onion virtports onto the local services we're willing to expose.
    ports = {}
    gw = node.apps.get("gateway")
    if gw is not None:
        ports[80] = f"127.0.0.1:{gw[2]}"                 # read-only projection
    if t.expose_write_services:                          # opt-in: `inbound: all`
        es, bs = node.apps.get("event_store"), node.apps.get("blob_store")
        if es is not None:
            ports[es[2]] = f"127.0.0.1:{es[2]}"          # relay (write surface)
        if bs is not None:
            ports[bs[2]] = f"127.0.0.1:{bs[2]}"          # blob store (write surface)
    if not ports:
        return None

    try:
        onion = OnionService(t.control_host, t.control_port, t.control_password)
        addr = onion.create(ports)
    except Exception as e:
        print(f"pijn: failed to publish hidden service ({e}); continuing without inbound onion")
        return None

    scope = "gateway only (read-only)" if not t.expose_write_services else "gateway + relay + blob"
    print(f"pijn: hidden service up — http://{addr}/  [{scope}]")
    for vp, target in sorted(ports.items()):
        print(f"        onion:{vp} -> {target}")
    return onion


def run(policy: Policy, only: str | None = None):
    """Build and serve the node (blocking)."""
    node = build_node(policy, only=only)
    if not node.apps:
        raise SystemExit("no services enabled")
    controller = build_controller(policy, node) if only is None else None
    names = ", ".join(
        f"{name} :{port}" for name, (_a, _h, port) in node.apps.items()
    )
    if controller is not None:
        names += f" | mirroring {len(policy.sites)} site(s)"
    print(f"pijn node up — {names}")
    onion = _start_onion(policy, node)
    try:
        asyncio.run(_serve_all(node, controller))
    finally:
        if onion is not None:
            onion.close()
        if node.store:
            node.store.close()
