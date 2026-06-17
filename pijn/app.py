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

    def wanted(name: str, enabled: bool) -> bool:
        return enabled and (only is None or only == name)

    if wanted("event_store", es.enabled):
        node.store = EventStore(es.db)
        node.apps["event_store"] = (build_relay_app(node.store, policy), es.host, es.port)

    if wanted("blob_store", bs.enabled):
        node.blob_store = BlobStore(bs.path)
        node.apps["blob_store"] = (
            build_blob_app(node.blob_store, policy.blossom_public_url,
                           max_size=policy.blob_max_size),
            bs.host, bs.port,
        )

    if wanted("gateway", gw.enabled):
        # If we have both local stores in-process, resolve locally; else remote.
        if node.store is not None and node.blob_store is not None:
            resolver = Resolver(
                LocalEventSource(node.store), LocalBlobSource(node.blob_store), is_async=False,
            )
        else:
            resolver = Resolver(
                RelayEventSource(policy.relays_read or [policy.relay_public_url]),
                HttpBlobSource(policy.blossom_servers or [policy.blossom_public_url]),
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
    from .replication import ReplicationController

    return ReplicationController(
        store=node.store, blob_store=node.blob_store, sites=policy.sites,
        source_relays=policy.relays_read or [policy.relay_public_url],
        default_blossom=policy.blossom_servers or [policy.blossom_public_url],
        storage_total=policy.storage_total,
    )


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
    try:
        asyncio.run(_serve_all(node, controller))
    finally:
        if node.store:
            node.store.close()
