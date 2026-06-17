"""
NIP-01 filters.

A relay subscription (`REQ`) carries one or more *filters*. An event matches a
filter when every present condition matches; a subscription matches when an
event matches ANY of its filters. Supported conditions:

    ids, authors, kinds            exact membership
    #<x> (single-letter tag)       event has a tag [<x>, value, ...] with value in the set
    since, until                   created_at bounds (inclusive)
    limit                          cap on returned events (newest first)

The event-store uses `build_query` for the columns it can index in SQL, then
`matches` in Python for tag conditions. Keeping the predicate here (rather than
inline SQL) keeps the matching rules in one auditable place.
"""


def _tag_filters(flt: dict):
    """Yield (single_letter, set_of_values) for each #x condition in a filter."""
    for key, values in flt.items():
        if len(key) == 2 and key[0] == "#":
            yield key[1], set(values)


def matches(event, flt: dict) -> bool:
    """True iff `event` (a nostr.Event) satisfies a single filter dict."""
    if "ids" in flt and event.id not in set(flt["ids"]):
        return False
    if "authors" in flt and event.pubkey not in set(flt["authors"]):
        return False
    if "kinds" in flt and event.kind not in set(flt["kinds"]):
        return False
    if "since" in flt and event.created_at < flt["since"]:
        return False
    if "until" in flt and event.created_at > flt["until"]:
        return False
    for letter, wanted in _tag_filters(flt):
        present = set(event.tag_values(letter))
        if present.isdisjoint(wanted):
            return False
    return True


def matches_any(event, filters: list) -> bool:
    return any(matches(event, f) for f in filters)
