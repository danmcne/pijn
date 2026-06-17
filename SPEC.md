# pijn — P0 architecture spec

**Status:** P0 (spec & decisions, no code). Freeze this before P1.
**Purpose of this doc:** pin every layer to a real published NIP/component, draw
the node's service boundaries, define the event-vs-blob data model, and lock the
replication-policy schema — so that "what we build" is unambiguous and your
colleague can sign off on the architecture.

The governing rule for every decision below: **does vanilla Nostr software still
understand this?** If the answer is ever "no," the decision is wrong.

---

## 1. Layer spec — each layer pinned to its component

Bottom-up. New protocol surface is intentionally near-zero; almost everything is
"adopt the spec."

| Layer | Pinned to | Kinds / endpoints | Notes |
|---|---|---|---|
| Identity & signing | Nostr keypair (secp256k1 / Schnorr), **NIP-01** event format | — | `nsec` is local-only; never reaches a server (§ cross-cutting). |
| Human names | **NIP-05** | — | DNS-backed `name@domain` → pubkey. Anti-impersonation via WoT. |
| Event transport (relay) | **NIP-01** relay protocol | `EVENT`/`REQ`/`CLOSE`/`EOSE`/`NOTICE` | + **NIP-42** `AUTH`, **NIP-50** search, **NIP-09** deletes. |
| Relay discovery | **NIP-65** relay-list metadata | kind **10002** | Outbox model: how the resolver finds *where* a pubkey's events live. |
| Immutable bytes (blob store) | **Blossom** (BUD series — *not a NIP*) | `GET`/`HEAD /<sha256>` (BUD-01), `PUT /upload` + `DELETE` (BUD-02), `PUT /mirror` (BUD-04) | Auth = kind **24242** event, base64 in `Authorization: Nostr …`, with `t`/`x`/`expiration` tags. |
| Blob-server discovery | **Blossom** BUD-03 | kind **10063** | A pubkey's preferred blob servers (the blob analogue of NIP-65). |
| Site manifest (the "site") | **NIP-5A** (nsite) | kind **15128** root, **35128** named, **34128** legacy | `path → sha256` map via `["path","/abs","hash"]` tags; optional `server`, `title`, `description`, `source`. **See delta D1.** |
| Blog | **NIP-23** long-form | kind **30023** | — |
| Wiki | **NIP-54** | kind **30818** | Built-in versioning + fork/merge + WoT. |
| Forum / community | **NIP-72** (reddit-style) **or NIP-7D** (usenet/threads) | kind **34550** (NIP-72) | **First app type after static + blog.** NIP-29 groups are a different, chat-shaped thing. **See delta D2.** |
| Shop catalog | **NIP-15** marketplace | kinds **30017** (stall) / **30018** (product) | Order flow + payment: **see delta D3**. |
| Tipping & payments | **NIP-57** Lightning zaps; **Cashu** — **NIP-87** mint announce (kind **38172**), **NIP-60** wallet, **NIP-61** nutzaps | zaps: kind **9734** (request) / **9735** (receipt) | Author zaps are vanilla; routing value to *seeders/hosts* is the new surface (P7). *città nostr* BDHKE/ecash plugs in here. |
| Git repos (optional) | **NIP-34** | — | P7 / optional. |
| Render — local | pijn resolver/gateway (we build, P1) | — | npub/identifier → relay-list → manifest → blobs → `localhost`. |
| Render — clearweb | **njump** (adopt/fork, P5) | — | Server-rendered, SEO-indexable; sitemaps from manifests. |

---

## 2. Node service boundaries

Four independent processes. The default install runs them in one daemon; any can
run alone. A fifth coordinator (replication controller) arrives in P3 and only
*drives* the others — it owns no storage of its own.

```
                         ┌─────────────────────────────────────────┐
                         │            pijn node (daemon)            │
                         │                                          │
   author / browser ───► │  ┌────────────┐      ┌────────────────┐  │
                         │  │ gateway /  │◄────►│  event-store    │  │  owns: events
                         │  │ resolver   │      │  (Nostr relay)  │  │  (SQLite)
                         │  │ (a *view*, │      └────────────────┘  │
                         │  │  no state) │      ┌────────────────┐  │
                         │  │            │◄────►│  blob-store     │  │  owns: blobs
                         │  └────────────┘      │  (Blossom)      │  │  (files, by sha256)
                         │        ▲             └────────────────┘  │
                         │        │             ┌────────────────┐  │
                         │  ┌─────┴──────┐      │  replication    │  │  owns: nothing
                         │  │ transport  │      │  controller     │  │  (P3; reads YAML,
                         │  │ direct/Tor │      │  (P3)           │  │   drives the two
                         │  └────────────┘      └────────────────┘  │   stores above)
                         │   (cross-cuts all outbound/inbound I/O)  │
                         └─────────────────────────────────────────┘
```

| Service | Responsibility | Interface | Owns | Default |
|---|---|---|---|---|
| **event-store** | Hold & serve signed events | NIP-01 relay over WebSocket; filter queries over SQLite | Events | Build in Python (P1); option to swap strfry/khatru for public nodes later. |
| **blob-store** | Hold & serve content-addressed bytes | Blossom HTTP (BUD-01/02/03/04), kind 24242 auth | Blobs | Build in Python (P1). |
| **gateway / resolver** | Turn a pubkey+identifier into a rendered site | HTTP at `localhost` (P1), clearweb (P5) | Nothing persistent — pure projection | Build (P1). |
| **transport** | Network reachability & privacy | SOCKS to Tor; `.onion` inbound (optional) | Connection policy | Direct + Tor in P4; I2P/Lokinet pluggable later. |
| **replication controller** *(P3)* | Mirror chosen sites, enforce caps/eviction/bandwidth | Reads YAML policy; calls event-store + blob-store | Nothing — orchestration only | Build (P3). |

Config/policy loader (the YAML in §4) is present from P1 and shared by all
services.

---

## 3. Data model — events vs blobs

This is the conceptual spine. Everything in pijn is exactly one of two things.

**A blob** is immutable, content-addressed bytes, named by its `sha256`. It has
no author, no timestamp, no semantics. It lives in Blossom. Because the hash *is*
the name, integrity is self-verifying and any server is interchangeable — this is
precisely what makes file-level mirroring and partial seeding clean.

**An event** is a signed JSON object owned by a pubkey, living in a relay. In
pijn an event plays one of three functional roles:

1. **Pointer / manifest** — an nsite manifest (kind 15128 / 35128) that maps site
   paths to blob hashes. *The "site" is this event.* It contains no bytes, only
   references.
2. **Revision** — the mutability mechanism. Replaceable (15128) and addressable
   (35128, keyed by `d` tag) events are superseded by the newest `created_at`
   for a given `(pubkey[, d])`. **Updating a site = re-signing a new manifest.**
   No blob is ever mutated; only pointers move.
3. **Application content** — the addressable records of an app type (30023 blog,
   30818 wiki, 30017/30018 shop, …), which may themselves embed blob references
   for media.

The binding chain:

```
identity (pubkey)  ──owns──►  events  ──reference by sha256──►  blobs
   └ mutable, replaceable        └ the only place mutability lives    └ immutable, permanent-iff-seeded
```

Consequence (the **honest persistence model**): a site update produces a new
manifest and orphans the old blobs. Orphaned blobs persist only while someone
chooses to seed them. "Censorship resistance" therefore means *takedown
resistance for content people value*, not blanket availability — and Cashu paid
pinning (P7) is the escape valve for content with no organic seeders.

---

## 4. Replication-policy schema (YAML)

Node-wide defaults plus per-site overrides. v1 partial seeding is **file-level**:
when a site exceeds its `storage_cap`, keep a subset (by recency/popularity),
evict the rest. No chunk-level swarm/DHT in v1.

```yaml
# pijn node replication policy
version: 1

identity:
  npub: npub1...                 # operator identity for this node
  nsec_source: file              # file | hardware | prompt — nsec never leaves the host

services:                        # which processes this install runs
  event_store: { enabled: true, listen: "127.0.0.1:4848", db: "./relay.sqlite" }
  blob_store:  { enabled: true, listen: "127.0.0.1:4849", path: "./blobs" }
  gateway:     { enabled: true, listen: "127.0.0.1:4850" }

transport:
  default: direct                # direct | tor
  tor:
    socks: "127.0.0.1:9050"
    inbound_onion: false         # expose relay/blob/gateway as a hidden service

limits:                          # node-wide ceilings
  storage_total: 20GB
  bandwidth_month: 200GB
  blob_max_size: 100MB

eviction:
  policy: lru                    # lru | popularity | manual
  protect_pinned: true

moderation:                      # always *knowing*; no blind storage in v1
  mode: opt-in                   # opt-in: carry only what allow-rules reach | opt-out: carry all but block-rules
  pubkeys:
    allow: []                    # npub whitelist — authors I carry
    block: []                    # npub blacklist — authors I refuse
  content:                       # per-item overrides, by event id or sha256
    allow: []                    # carry this item even if its author isn't whitelisted / is blacklisted
    block: []                    # refuse this item regardless of its author
  warn_on_override: true         # warn when a content.allow item overrides a blacklisted author

relays:                          # where this node reads/writes events
  read:  ["wss://relay.damus.io", "wss://nos.lol"]
  write: ["wss://relay.damus.io"]

blossom:                         # default blob servers for publish/fetch
  servers: ["https://cdn.satellite.earth"]

sites:                           # each entry is a site this node chooses to host
  - name: my-blog
    pubkey: npub1...
    identifier: ""               # "" = root site (kind 15128); else named (kind 35128)
    seed: true                   # serve this site's blobs + manifest to others
    pin: true                    # never evicted; ignores storage_total/eviction
    storage_cap: 2GB             # file-level cap; subset kept if site exceeds it
    transport: direct            # per-site override of transport.default
    refresh: 15m                 # how often to re-pull the manifest for updates

  - name: someones-wiki
    pubkey: npub1...
    identifier: "notes"
    seed: false                  # mirror for myself only; do not serve to others
    pin: false
    storage_cap: 500MB
    transport: tor
```

`seed: false` = "I keep a copy but don't advertise/serve it." `pin: true` =
"never evict, ignore caps." Absence of a `pin` with a `storage_cap` smaller than
the site triggers file-level partial seeding.

**Moderation precedence** (most specific wins, top to bottom):

1. `content.block` — never carry this item. Absolute.
2. `content.allow` — carry this item even if its author isn't whitelisted, or is
   blacklisted. If the author is in `pubkeys.block`, carry it but emit a warning
   (when `warn_on_override`).
3. `pubkeys.block` — don't carry this author's other content.
4. `pubkeys.allow` — carry this author (the inclusion mechanism in `opt-in` mode).
5. `mode` default — `opt-in`: carry nothing else; `opt-out`: carry everything not
   blocked above.

So "I saw one post I like from someone I don't follow / have blocked" is a
single `content.allow` entry, not a change to the author lists.

---

## 5. Decisions — frozen vs open

**Frozen (carried from roadmap v1 scope + this round):** Blossom whole-blob,
file-level partial seeding only; transport = Direct + Tor (I2P/Lokinet deferred
but pluggable); ship static site + blog first; no blind/encrypted-unknowable
storage in v1; no chunk-level swarm/DHT in v1. **Relay: built in Python for v1,
with I/O consistent with a standard relay so strfry/khatru drop in for public
nodes later.** **Clearweb gateway: adopt njump.** **First app type after
static+blog: forum** (reddit/usenet-style — see D2). **Moderation: mode +
npub allow/block + per-content overrides** (§4).

**Deltas surfaced during P0 (confirm at sign-off):**

- **D1 — nsite kinds.** The roadmap pins "kind 35128," but NIP-5A defines **15128
  = root site** (one replaceable root per pubkey) and **35128 = named site**
  (addressable sub-sites via `d` tag); **34128 is the deprecated legacy kind.**
  *Recommend:* default publish to 15128 (root) + 35128 (named); read 34128 for
  back-compat only.
- **D2 — forum standard.** Forum is now the **first app type after static+blog**.
  The lean is reddit/usenet, which points at **NIP-72** (moderated communities,
  reddit-style, kind 34550) or **NIP-7D** (Forum Threads, usenet-style) — *not*
  NIP-29 (relay-based groups), which is a chat-group shape. Caveat: NIP-72 is
  flagged *upstream* as unrecommended in favour of NIP-29; weigh that against
  actual client support. **Decision (NIP-72 vs NIP-7D) deferred to P6 entry, not
  frozen now.**
- **D3 — shop order/payment split.** NIP-15 carries its own order/checkout
  messaging; **NIP-69** (kind 38383) is a *separate* P2P-order standard, not the
  NIP-15 storefront flow. *Recommend:* v1 shop = NIP-15 catalog + native order
  flow + Cashu (NIP-87/60/61) for payment; treat NIP-69 + escrow/reputation as
  the P7 research track (the genuinely unsolved part that sank OpenBazaar).

**Still open (your call):** which forum NIP — NIP-72 (reddit-style) vs NIP-7D
(usenet/threads) — decided at P6 entry (see D2); whether unified author/host
tipping (NIP-57 zaps + Cashu) lands in P6 (if template-only) or as the first item
of P7 (once it routes value to seeders/hosts).

---

## 6. Exit criteria for P0

Sign-off on: (1) the layer pin table in §1 including deltas D1–D3, (2) the four
service boundaries in §2, (3) the event-vs-blob model in §3, (4) the YAML schema
in §4. Once signed, P1 (node skeleton) may begin.
