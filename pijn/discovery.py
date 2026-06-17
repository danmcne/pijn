"""
Discovery (P3 basics) — find where an identity publishes, via NIP-65.

To mirror someone's site you must first find a relay that carries their events.
NIP-65 (kind 10002) is the standard answer: each identity publishes a small
"relay list" event with `r` tags naming its read and write relays (the "outbox
model"). Given one bootstrap relay, a seeder reads the author's kind-10002 and
learns the author's own write/outbox relays — where their manifests and posts
actually live — instead of needing the operator to hardcode them.

This is deliberately minimal: relay discovery only. Discovering *other seeders*
holding a site (beyond the blob `server` hints already in the manifest) needs a
host-announcement protocol, which is the deferred `seed`-advertisement work; the
shape here (a verified, authored, replaceable list event) is the same it will
take.
"""

from .client.relay_client import RelayClient
from .nostr.event import make_event

KIND_RELAY_LIST = 10002
KIND_SEED = 30888  # pijn seed announcement (addressable); a node advertising it
                   # hosts a given site. Non-standard — a pijn extension (SPEC D4).


def site_coord(site_kind: int, author_pubkey: str, identifier: str) -> str:
    """NIP-01 addressable coordinate for a site: `kind:pubkey:identifier`."""
    return f"{site_kind}:{author_pubkey}:{identifier}"


def relays_from_event(event) -> dict:
    """Parse a kind-10002 into {'read': [...], 'write': [...]} (NIP-65 `r` tags)."""
    read, write = [], []
    for tag in event.tags:
        if len(tag) >= 2 and tag[0] == "r":
            url = tag[1]
            marker = tag[2] if len(tag) >= 3 else ""
            if marker in ("", "write"):
                write.append(url)
            if marker in ("", "read"):
                read.append(url)
    return {"read": read, "write": write}


async def discover_relays(pubkey: str, seed_relays: list, want: str = "write") -> list:
    """Find a pubkey's relays via its newest kind-10002 across `seed_relays`.

    `want='write'` returns the author's outbox relays — where to look for the
    events they publish (manifests, posts).
    """
    newest = None
    for url in seed_relays:
        try:
            events = await RelayClient(url).query(
                [{"authors": [pubkey], "kinds": [KIND_RELAY_LIST], "limit": 1}])
        except Exception:
            continue
        for ev in events:
            if ev.verify() and ev.pubkey == pubkey and (
                    newest is None or ev.created_at > newest.created_at):
                newest = ev
    if newest is None:
        return []
    return relays_from_event(newest).get(want, [])


def build_relay_list_event(read_relays: list, write_relays: list):
    """Build an *unsigned* kind-10002 relay-list event for this identity."""
    rset, wset = set(read_relays), set(write_relays)
    tags = []
    for url in sorted(rset | wset):
        if url in rset and url in wset:
            tags.append(["r", url])           # both
        elif url in wset:
            tags.append(["r", url, "write"])
        else:
            tags.append(["r", url, "read"])
    return make_event(KIND_RELAY_LIST, content="", tags=tags)


def build_seed_announcement(site_kind: int, author_pubkey: str, identifier: str,
                            servers: list, relays: list):
    """Build an *unsigned* seed announcement: "this node hosts that site".

    Signed by the *seeder* (not the author); keyed (`d`) by the site coordinate
    so each seeder has one current announcement per site. Carries the seeder's
    blob `server`s (where its copy of the blobs can be fetched) and `relay`s
    (where its copy of the manifest/posts can be read).
    """
    coord = site_coord(site_kind, author_pubkey, identifier)
    tags = [["d", coord], ["a", coord], ["p", author_pubkey]]
    tags += [["server", s] for s in servers]
    tags += [["relay", r] for r in relays]
    return make_event(KIND_SEED, content="", tags=tags)


async def discover_seeders(coord: str, relays: list) -> list:
    """Find nodes announcing they seed the site `coord`.

    Returns [{'pubkey', 'servers', 'relays'}] from verified announcements — the
    extra blob servers and relays a mirrorer can pull from when the author's own
    endpoints are unavailable.
    """
    seen, out = set(), []
    for url in relays:
        try:
            events = await RelayClient(url).query(
                [{"kinds": [KIND_SEED], "#a": [coord], "limit": 100}])
        except Exception:
            continue
        for ev in events:
            if ev.id in seen or not ev.verify():
                continue
            seen.add(ev.id)
            out.append({
                "pubkey": ev.pubkey,
                "servers": [t[1] for t in ev.tags if len(t) >= 2 and t[0] == "server"],
                "relays": [t[1] for t in ev.tags if len(t) >= 2 and t[0] == "relay"],
            })
    return out
