# Changelog

All notable changes to pijn are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/); this project versions by
roadmap phase (see [`roadmap.md`](./roadmap.md)).

## [0.3.0] — P3: replication & seeding

A node can now mirror other people's sites and keep them reachable while their
author is offline — the P3 exit criterion, verified with a two-node test (node A
serves node B's site and blog after B is killed).

### Added
- **Replication controller** (`replication.py`): the fifth, state-less
  coordinator. For each entry under `sites:` it pulls the manifest (and, for an
  `app=blog`, the kind-30023 posts) from source relays and the blobs from
  Blossom servers, writing them into this node's own stores — after which the
  local gateway serves them. Everything pulled is verified before storage
  (event signatures via `Event.verify()`, blob bytes via the content-address
  check), so source relays/servers need not be trusted.
- **`pijn sync`**: one-shot mirror of every configured site, with a per-site
  report. `pijn run` also mirrors in the background (on startup, then on each
  site's `refresh` cadence) when `sites:` is non-empty and local stores exist.
- **Storage caps** (SPEC §4): `pin: true` bypasses all caps; otherwise a per-site
  `storage_cap` triggers **file-level partial seeding** (files taken in manifest
  order until the cap is hit, the rest skipped) and `limits.storage_total` is a
  hard node ceiling. Policy parses `sites`, `limits.storage_total`, and `refresh`
  durations (`15m`/`1h`/`2d`).
- Supporting helpers: `BlobStore.total_bytes()`, `BlossomClient.head()`.

### Notes / deferred to 0.3.1
- `seed` is recorded but, with no announcement protocol yet, governs only future
  advertisement — a content-addressed store serves any blob by hash, and blobs
  are shared across sites, so per-site serve-suppression isn't meaningful yet.
- Active LRU/popularity **eviction** (the controller currently enforces ceilings
  by not exceeding them rather than evicting), **bandwidth budgets**, and
  **seeder/relay discovery** ("find who else holds a site") are the remaining P3
  items; hooks are in place.

## [0.2.2] — P2 close: named-site reachability + docs

### Changed
- **Named sites are now served under the path URL** (`/s/<npub>/<id>/`) instead
  of redirecting to the nested `<id>.<npub>.<host>` subdomain
  (`gateway/server.py`). Nested `.localhost` names don't resolve reliably across
  browsers, so the path form is the dependable local route; gateway-rendered
  blogs and relative-link sites resolve correctly under the prefix (a `/s/.../id`
  request without a trailing slash 307s to add one, preserving relative links).
  The nested subdomain remains the canonical address and still works where it
  resolves. Root sites still redirect to `<npub>.<host>` (single-level, reliable).

### Docs
- README rewritten around **root vs named sites**: the one-root-manifest-per-key
  rule (why a root blog replaces a root static site), explicit `--identifier`
  examples for both `publish` and `blog`, and both addressing forms with guidance
  on which to use locally.

## [0.2.1] — P2: blog template (kind 30023) — P2 exit met

Adds long-form blogging as a *projection*: posts are kind-30023 events (readable
by any NIP-23 client), and the gateway renders them to a site on the fly. This
meets the P2 exit — a non-trivial site, editable in place, visible to a vanilla
Nostr client.

### Added
- **Blog projection** (`gateway/blog.py`, `gateway/resolver.py`): an nsite
  manifest tagged `app=blog` marks an origin as a blog; the resolver then queries
  the owner's kind-30023 events and renders an index (`/`) plus per-post pages
  (`/<slug>`) instead of serving blobs. Byline always shows the npub digest.
- **Markdown renderer** (`gateway/markdown.py`): small, vendored, pure-Python
  CommonMark subset. All text is HTML-escaped and URLs are sanitized
  (`javascript:`/`data:` neutralized) — the gateway renders untrusted authors'
  Markdown, and per-site origins contain the rest.
- **Authoring** (`post.py`): `pijn post <file.md>` publishes/updates a kind-30023
  post (slug = `d` tag; re-posting supersedes); `pijn blog` publishes the
  `app=blog` manifest. `pijn init --template blog` scaffolds a sample post.

### Notes
- A blog is, for now, *all* of the author's kind-30023 posts. Curated/multiple
  blogs (via NIP-51 sets or `a`-tag references) are a later refinement.
- `published_at` is set to now on each publish; preserving the original across
  edits is a small follow-up.

## [0.2.0] — P2 (in progress): per-site origins + templated publishing

Begins P2 (author → publish → update from a template). The gateway naming model
is finished and the publishing path is real; the blog (kind 30023) template is
the next slice.

### Added
- **Named-site origins** (`gateway/server.py`): each site now has its own
  origin — `http://<npub>.<host>/` for a root site, `http://<id>.<npub>.<host>/`
  for a named site — so a site's root-absolute links (`/style.css`) resolve to
  that site. The pubkey may be the first or second host label, so it works under
  `*.localhost` and a multi-label clearweb domain alike.
- **Templated publisher** (`publish.py`): uploads now carry a detected
  content-type (so vanilla Blossom clients and njump serve blobs correctly), and
  `publish --server <url>` can target an external Blossom host. Re-publishing is
  the mutable-update path: a fresh manifest with a newer `created_at` supersedes
  the old one — no blob is mutated.
- **`init` command + `static` template** (`templates.py`): `pijn init <dir>`
  scaffolds a clean, build-step-free starter site (relative links, dark-mode
  aware) the author edits and publishes. More templates follow.

### Changed
- **Legacy path routes now redirect** (`gateway/server.py`): `/n/<npub>/…` and
  `/s/<npub>/<id>/…` issue a 307 to the canonical per-site origin instead of
  rendering, so an old or hand-typed link lands on the working URL rather than a
  half-broken one (the path scheme could never carry root-absolute assets).
- `publish` prints the canonical subdomain URL for both root and named sites.

## [0.1.2] — P1 hardening + naming primitives

Post-review hardening of the P1 skeleton, plus the first naming pieces (the
NIP-05 + web-of-trust direction agreed for discovery; engine itself is P6).

### Fixed
- **NIP-01 replaceable/addressable tie-break** (`event_store/db.py`): on equal
  `created_at` the lexicographically *smallest* id is now retained, per NIP-01.
  Previously the larger id won.
- **Blob integrity on fetch** (`client/blossom_client.py`): a fetched blob is
  now re-hashed and rejected on mismatch, so a lying/buggy Blossom server can't
  serve arbitrary bytes for a hash (the assumption the mirror model relies on).
- **Client hang protection** (`client/relay_client.py`): `publish`/`query` take
  a timeout and terminate on `CLOSED`/`NOTICE`; no more indefinite hangs.
- **`blob_max_size` enforced** (`policy.py`, `app.py`, `blob_store/server.py`):
  oversized uploads are rejected with 413 (Content-Length pre-check + post-read
  backstop). Added a `parse_size` helper for human sizes (`100MB`, `20GB`).
- **BIP-340 signing** (`nostr/event.py`): `Event.sign` now uses fresh `aux_rand`
  for side-channel hardening; `schnorr_sign` keeps a zero default so the test
  vectors still reproduce.

### Added
- **Gateway subdomain origin** (`gateway/server.py`): a Host-header router serves
  `http://<npub>.<host>/…` as that pubkey's root site, giving each site its own
  origin so root-absolute links (`/style.css`) resolve. Path routes
  (`/n/…`, `/s/…`) are unchanged. `publish` prints the subdomain URL for root
  sites. This is the model the clearweb gateway (P5) will reuse.
- **NIP-05** (`nostr/nip05.py`): resolve `name@domain` → pubkey (+ outbox relay
  hints), and `verify_nip05` to confirm a domain's vouch. No HTTP redirects.
- **Name display** (`nostr/display.py`): `short_npub` (key-derived digest) and
  `name_badge`, enforcing the rule that a claimed name is always shown beside
  the unfakeable npub digest.
- **`whois` CLI**: resolve a NIP-05 or show an npub digest, the way a UI would.
- **`relays.trusted`** policy field (parsed inert) — seeds the future web of
  trust. **SPEC §7** records the naming/discovery model.

## [0.1.0] — P1: node skeleton

The first running code. Three separable services plus the tooling to publish and
browse a site locally.

### Added
- **Nostr core** (`pijn/nostr/`), pure-Python with no native crypto dependency:
  - BIP-340 Schnorr signatures over secp256k1 (`schnorr.py`).
  - bech32 `npub`/`nsec` encoding, NIP-19 (`bech32.py`).
  - keypair generation and management (`keys.py`).
  - event model: id computation, signing, verification, and NIP-01
    classification — regular / replaceable / addressable / ephemeral
    (`event.py`).
  - NIP-01 filter matching (`filters.py`).
  - nsite manifest build/parse/resolve, kinds 15128 (root) / 35128 (named),
    with legacy 34128 read support (`nsite.py`).
- **Event-store service** (`pijn/event_store/`):
  - SQLite persistence enforcing replaceable/addressable storage rules and a
    single-letter tag index for `#x` filters (`db.py`).
  - minimal NIP-01 WebSocket relay — EVENT / REQ / CLOSE → OK / EVENT / EOSE /
    CLOSED / NOTICE — with a live subscription hub (`relay.py`).
- **Blob-store service** (`pijn/blob_store/`):
  - content-addressed storage by sha256 with SQLite metadata (`storage.py`).
  - Blossom HTTP server: PUT `/upload`, GET/HEAD `/<sha256>`, DELETE,
    GET `/list/<pubkey>` (`server.py`).
  - kind-24242 authorization verification (`auth.py`).
- **Gateway service** (`pijn/gateway/`):
  - resolver with pluggable local (in-process) and remote (relay/HTTP) sources,
    so it works co-resident or standalone (`resolver.py`).
  - local renderer serving sites at `/n/<npub>/…` and `/s/<npub>/<id>/…`
    (`server.py`).
- **Clients** (`pijn/client/`): WebSocket relay client and HTTP Blossom client
  with host-side signing.
- **Policy loader** (`pijn/policy.py`): parses the SPEC §4 YAML; later-phase
  sections load inertly. The `nsec` is read only from `PIJN_NSEC` or the
  `nsec_file`, never from the policy document.
- **Composition + CLI** (`pijn/app.py`, `pijn/__main__.py`): `run` (together or
  `--only` one service, each on its own port), `keygen`, `pubkey`, `publish`.
- **Minimal publisher** (`pijn/publish.py`): directory → blobs → signed manifest
  → relay, over the real wire interfaces. (P2 replaces it with a templated
  publisher.)
- Supporting files: `requirements.txt`, `policy.example.yaml`, `examplesite/`.

### Notes
- **P1 exit met:** publish a static site and browse it locally; verified
  end-to-end (Blossom HTTP upload + relay WebSocket publish + byte-identical
  gateway render) and with service separability.
- Crypto is pure-Python for zero native dependencies; a C binding can drop in
  behind the same `schnorr_*` interface for high-throughput public nodes — the
  same "build for v1, keep the option open" stance taken for the relay.

## [P0] — spec & decisions

### Added
- `SPEC.md`: layer pin table, four-service architecture, event-vs-blob data
  model, the YAML replication-policy schema, and exit criteria.
- `roadmap.md`, `README.md`: project plan and front door.

### Decided
- Relay built in Python for v1 with standard I/O, so a hardened relay can drop in
  later; clearweb gateway adopts njump; first app type after static + blog is a
  reddit/usenet-style forum.
- Layered moderation: opt-in/opt-out base + npub allow/block + per-content
  overrides (with override warnings).
- Tipping spans authors *and* hosts/seeders (NIP-57 zaps + Cashu).

### Verified against live specs (deltas folded into SPEC)
- D1: nsite kinds — 15128 root (replaceable), 35128 named (addressable), 34128
  deprecated.
- D2: forum standard left open between NIP-72 (reddit-style) and NIP-7D
  (usenet/threads); NIP-29 is a different, chat-shaped thing.
- D3: NIP-69 P2P orders are distinct from the NIP-15 storefront order flow.
