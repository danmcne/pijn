# Changelog

All notable changes to pijn are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/); this project versions by
roadmap phase (see [`roadmap.md`](./roadmap.md)).

## [0.4.0] — P4 transport: outbound Tor + cautious inbound onion

Phase 4. Tor is added in two independent halves, with the inbound half
deliberately read-only-first per the "err on the side of caution" plan: start by
exposing only the gateway, open the writable ports later. No data-format or
on-disk changes; existing identities and stores carry over.

### Added
- **Transport layer** (`pijn/transport/`): a `Transport` config parsed from the
  policy `transport:` block, a `proxy_url`/`proxy_for_url` helper (loopback
  targets are never tunnelled; `.onion`/DNS resolve inside Tor via `socks5h`),
  and a small dependency-free Tor **control-port client** that publishes an
  ephemeral hidden service via `ADD_ONION`.
- **Outbound Tor.** `transport.default: direct|tor` routes this node's relay (WS)
  and Blossom (HTTP) client connections — replication, discovery, and `announce`
  — through the Tor SOCKS proxy, and can reach `.onion` peers. Overridable per
  mirrored site with `sites[].transport`. The relay client uses websockets'
  native SOCKS support; the Blossom client uses `httpx[socks]`.
- **Inbound hidden service (opt-in, read-only first).**
  `transport.tor.inbound_onion`:
  - `off` (default) — no inbound onion.
  - `gateway` — publish **only** the read-only gateway as an `.onion`.
  - `all` — additionally expose the writable relay + blob ports (explicit opt-in).
  The onion is ephemeral (gone on exit). If the Tor control port is unreachable,
  the daemon logs a warning and continues serving without an onion.
- README gained a **Privacy & Tor** section; the example policy's `transport:`
  block documents the SOCKS/control/inbound options.

### Changed
- `transport.tor.inbound_onion` accepts the strings `off|gateway|all`; the old
  boolean still works (`true` → `gateway`, `false` → `off`).
- The publisher (`publish`/`post`/`blog`) continues to write to the **local**
  node directly — it is a local operation, so it is never tunnelled.

### Dependencies
- Added `httpx[socks]` (pulls in `socksio`) and `python-socks` for SOCKS support
  in the HTTP and WebSocket clients. Both are wheels; still no build step.
  Inbound onion uses Tor's control port directly and needs no extra dependency.

### Not yet exercised
- A **live Tor round-trip** was not run in the development environment (no Tor
  daemon there): the SOCKS outbound path and `ADD_ONION` are verified by API/
  protocol conformance and against a mock control server, not against real Tor.
  The gateway-first rollout is the intended way to validate it in practice.

## [0.3.4] — hardening pass before P4 (audited crypto, real moderation, SSRF/XSS fixes)


A security and correctness pass gating entry to P4. P4 makes the node *reachable*
(inbound `.onion`), which invalidates the "fine for a local personal node"
assumption behind several earlier shortcuts — so they are addressed now, before
any transport code lands. No data-format or on-disk changes; existing identities
and stores carry over untouched.

### Changed
- **Cryptography is no longer hand-rolled on the hot path.** Signing and
  verification now use **libsecp256k1 via `coincurve`** (the audited C library
  Bitcoin Core uses); the at-rest nsec is sealed with **pyca/cryptography**
  (ChaCha20-Poly1305 + scrypt). Both ship as pre-built wheels, so there is still
  **no build step**. The previous pure-Python BIP-340 / ChaCha20-Poly1305 code is
  retained only as an automatic fallback (`_schnorr_fallback.py`,
  `_cipher_fallback.py`) used when a wheel is unavailable; it warns on stderr.
  `schnorr.BACKEND` / `cipher.BACKEND` report which is live. Existing
  `nsec.enc` files decrypt unchanged (the container format is identical).
- **Key-encryption container now records and honors its KDF.** v0.3.3 always
  wrote `kdf: scrypt` but could silently re-derive with a different KDF across
  environments, risking permanent lockout. The container is now self-describing
  (`v: 2`) and decrypt re-derives exactly as written; v1 containers still read.
- **The example moderation default is now `opt-out`** (carry all not explicitly
  blocked). The prior `opt-in` example with empty allow-lists would, now that
  moderation is enforced, carry *nothing* — a footgun for anyone copying it.

### Added — security
- **Moderation is now enforced** (it was parsed but inert in 0.3.x). The relay
  ingest, Blossom upload, and replication all consult the policy with the SPEC §4
  precedence (`content.block > content.allow > pubkeys.block > pubkeys.allow >
  mode`). `warn_on_override` logs when a `content.allow` carries a blocked
  author's item. (`pijn/moderation.py`)
- **SSRF guard on network-discovered endpoints** (`pijn/netguard.py`). Blob
  servers and relays learned from manifests and kind-30888 seeder announcements
  are refused if they resolve to loopback/private/link-local/reserved addresses.
  Operator-configured endpoints are trusted and exempt; `.onion` passes (routed
  over Tor in P4). Relax for local testing with
  `replication.allow_private_sources: true`.
- **Markdown XSS fixed.** The long-form renderer's URL filter is now a scheme
  *allowlist* (`http`/`https`/`mailto`/relative) and strips embedded control
  characters first, closing `java\tscript:`-style scheme-spoofing that bypassed
  the old denylist. Also fixed a double-escape that corrupted `&` in URLs.
- **Gateway security headers.** All served responses carry `X-Content-Type-Options:
  nosniff` and `Referrer-Policy: no-referrer`; pijn-generated HTML (blog/landing)
  additionally gets a strict `Content-Security-Policy` (no scripts) and
  `X-Frame-Options: DENY`; raw author blobs get `X-Frame-Options: SAMEORIGIN`.
- **Relay ingest guardrails** for when the node becomes reachable: per-connection
  subscription cap, per-REQ filter cap, a default + maximum query `limit` so a
  broad `REQ` can't stream the whole store, and rejection of events dated far in
  the future. (The built-in relay remains a personal-node relay; strfry/khatru
  still drop in for public nodes.)
- **Blob hash-name validation** at the HTTP boundary (`^[0-9a-f]{64}$`) as
  defence-in-depth against path traversal, and a **hard streaming size cap** on
  replication fetches so a server that under-reports its size in HEAD can't make
  a mirroring node buffer an unbounded body.

### Added — correctness
- **NIP-09 deletions** (kind 5) are honored: a deletion removes the *same
  author's* referenced events (by `e` id and `a` coordinate); it can never
  delete another pubkey's content.
- Blog index no longer crashes on a non-numeric `published_at` tag; the relay
  client skips a malformed inbound `EVENT` instead of aborting the query.

### Dependencies
- Added `coincurve>=20` and `cryptography>=42` (both wheels; no compiler needed).

## [0.3.3] — persistent data home + encrypted key at rest

### Changed
- **All data lives under `~/.pijn/<npub>/`** (`keystore.py`): the encrypted key,
  relay db, blob store, and bandwidth state, partitioned by operator identity, so
  reinstalling or upgrading the code never touches your data and one machine can
  host several node identities. Override the root with `PIJN_HOME`. The example
  policy no longer hardcodes `db`/`path` (they default into the data home).
- **The nsec is encrypted at rest** (`nostr/cipher.py`): a vendored, dependency-
  free ChaCha20-Poly1305 (RFC 8439, verified against the spec vectors) with an
  scrypt-derived key. `keygen` prompts for a passphrase; signing commands unlock
  the key with it (or `PIJN_PASSPHRASE` for automation, or a plaintext
  `PIJN_NSEC`). The **npub stays plaintext** (`~/.pijn/<npub>/npub` and the dir
  name), so `pubkey` and path resolution need no passphrase, and the **daemon
  (`run`) never needs the key** — it serves and mirrors unattended.

### Added
- **`pijn identities`** lists the keys under `~/.pijn` (marking the active one);
  `--use <npub>` switches the active identity.

### Migrating from ≤0.3.2
- Old nodes kept a plaintext `./.pijn/nsec` and data in the working directory.
  To carry an identity over: run `pijn keygen`, choose overwrite → import, and
  paste the nsec from your old `./.pijn/nsec`; set a passphrase. Then re-publish
  / re-`sync` (or move the old `relay.sqlite`/`blobs` into `~/.pijn/<npub>/`).

## [0.3.2] — P3 close: seeder discovery, bandwidth budgets, default relays

This finishes P3. A site can now stay up purely because a *third party* seeds it.

### Added
- **Seeder discovery** (`discovery.py`, SPEC delta **D4**): a node advertises the
  sites it hosts with an addressable **kind-30888** seed announcement (signed by
  the seeder, keyed by the site coordinate, carrying its blob `server`s and
  `relay`s). `pijn announce` now publishes one per `seed: true` site alongside
  the NIP-65 relay list. The controller queries `#a` for a site's seeders and
  adds their relays/servers to its pull set — so a mirrorer can fetch a site from
  another seeder with the **author offline**. Verified with a four-node test
  (author down; a fresh node knowing only a shared relay discovers the seeder and
  serves the full site).
- **Bandwidth budget** (`bandwidth.py`): `limits.bandwidth_day` and
  `bandwidth_month` cap replication downloads, metered in a small JSON file that
  rolls over on the UTC day/month and survives restarts. Checked before each
  fetch (applies even to pinned sites — bandwidth is a hard external limit).

### Changed
- **Default relays** in the example policy: your local relay plus
  `relay.damus.io`, `nos.lol`, `relay.primal.net`, `relay.nostr.band`, so
  discovery and `announce` reach the wider network out of the box.
- Lower default `limits` now include `bandwidth_day: 1GB` (with `bandwidth_month: 10GB`).

### Note
- Seed announcements point at the node's configured blob/relay URLs; on a
  loopback-only setup those are `127.0.0.1`, so cross-machine seeding needs
  publicly reachable URLs — which is exactly what P4 (transport: Direct/Tor)
  provides.

## [0.3.1] — P3: discovery, interactive keygen, eviction config

### Added
- **Relay discovery (NIP-65)** (`discovery.py`): the controller now reads each
  site author's kind-10002 relay list to find their outbox relays, so it can
  mirror a site knowing only a shared/indexer relay — verified with a three-node
  test (seeder discovers the author's relay and mirrors without it configured).
  New `pijn announce` publishes this node's own relay list so others can find it.
- **Configurable eviction** (`eviction.py`): `eviction.policy` selects how room
  is made under `limits.storage_total`. Default **manual** (never auto-evict —
  the operator prunes, matching the opt-in model); `lru` and `popularity`
  (currently LRU-backed until access stats exist) plug in behind one function.
  `protect_pinned` shields pinned sites' blobs. Wired into `sync`/`run`.

### Changed
- **`keygen` is now interactive**: if an identity already exists it offers
  keep-or-overwrite, and **verifies** a kept key with a real sign/verify check
  (reporting clearly if it doesn't work); a corrupt key file is detected and a
  replacement offered. Creating a new identity asks whether to **import an
  existing nsec** (validated before it's written) or generate a fresh one.
  `keygen --force` keeps the old non-interactive "overwrite with a new key".
- **Lower default ceilings** in the example policy: `storage_total: 2GB`,
  `bandwidth_month: 10GB` (raise as you choose to host more); example
  `eviction.policy` is now `manual`.

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
