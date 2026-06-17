"""
Eviction strategies (P3).

When a node is over its `limits.storage_total`, an eviction strategy decides
which non-pinned blobs to drop to get back under. The default is **manual**:
nothing is auto-evicted — the controller simply stops mirroring more (it's the
operator's job to prune), which fits the opt-in model where the operator chose
what to mirror in the first place.

Other strategies plug in here by name (`eviction.policy` in the policy file):
- `manual`     — never auto-evict (default).
- `lru`        — evict least-recently-stored first.
- `popularity` — evict least-accessed first; until access stats exist it falls
                 back to LRU (the hook and shape are here so stats can drop in).

`protected` is the set of blob hashes that must never be evicted (blobs of
pinned sites); `protect_pinned` in policy controls whether that set is honored.
A strategy returns the list of sha256s to evict, oldest/least-valuable first,
just enough to free `need_bytes`.
"""

POLICIES = ("manual", "lru", "popularity")


def select_evictions(entries: list, need_bytes: int,
                     policy: str = "manual", protected=()) -> list:
    """Pick blobs to evict. `entries`: dicts with sha256/size/uploaded_at[/hits]."""
    if policy == "manual" or need_bytes <= 0:
        return []
    protected = set(protected)
    candidates = [e for e in entries if e["sha256"] not in protected]

    if policy == "popularity":
        # No access stats yet — order by hits if present, else fall through to
        # recency. This keeps the interface stable for when stats land.
        candidates.sort(key=lambda e: (e.get("hits", 0), e.get("uploaded_at", 0)))
    else:  # lru
        candidates.sort(key=lambda e: e.get("uploaded_at", 0))

    out, freed = [], 0
    for e in candidates:
        if freed >= need_bytes:
            break
        out.append(e["sha256"])
        freed += e.get("size", 0)
    return out
