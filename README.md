# pijn

**A self-hostable decentralized web where identities own signed content, users
choose how much of the network they support, and a "website" is just one way of
rendering that content.** Built *on* Nostr, not beside it.

> **Status:** v0.3.3 — P3 complete, now with all data under `~/.pijn/<npub>/`
> (survives reinstalls) and the **nsec encrypted at rest** (vendored
> ChaCha20-Poly1305 + scrypt; daemon runs without it). On top of P2 (per-site
> origins; templated `static`/`blog` publisher), a **replication controller**
> mirrors others' sites, discovers their relays and seeders (NIP-65 + kind-30888,
> `pijn announce`), and keeps a site reachable when its **author** is offline —
> with `pin`, `storage_cap`, eviction, and bandwidth budgets. Next is P4
> (transport: Direct/Tor). See
> [`SPEC.md`](./SPEC.md) for the frozen architecture,
> [`roadmap.md`](./roadmap.md) for the full plan, and [`CHANGELOG.md`](./CHANGELOG.md)
> for what landed in each phase.

---

## The idea

Most decentralized-web projects die of the cold-start problem: they seed an empty
network and wait for users who never come (ZeroNet, OpenBazaar, …). pijn refuses
to start cold. Every layer rides a real, published Nostr spec, so existing
relays, Blossom servers, clients, and gateways understand pijn content *the day
it ships*. We join a populated network instead of building a lonely one.

The model is closer to BitTorrent than to "the cloud." Content survives because
someone chooses to seed it — not because a publisher decreed it permanent. Each
participant decides, in one YAML file, how much storage and bandwidth to give,
which sites to mirror, and whether to route over Tor.

## How it fits together

A pubkey owns **events** (signed JSON, mutable, on relays). Events point — by
`sha256` — at **blobs** (immutable bytes, on Blossom servers). A "site" is just a
manifest event mapping paths to blob hashes; updating it means re-signing a new
manifest. Mutability lives entirely in events; permanence lives in blobs. That
single split is the whole data model ([`SPEC.md` §3](./SPEC.md)).

Some sites aren't blob-manifests at all. A **blog** is a manifest tagged
`app=blog` with no paths: the gateway *projects* the owner's long-form events
(kind 30023) into pages on the fly. The website is one rendering of the content;
the same events render in any NIP-23 client too.

| Layer | Rides on |
|---|---|
| Identity, signing, names | Nostr keys (NIP-01), NIP-05 |
| Events & discovery | Nostr relays (NIP-01), NIP-50 search, NIP-65 relay lists |
| Immutable bytes | Blossom (sha256 blobs, kind 24242 auth) |
| The "site" | nsite / NIP-5A (kinds 15128 root, 35128 named) |
| Apps | forum 34550 / NIP-7D · blog 30023 · wiki 30818 · shop 30017/30018 |
| Payments | NIP-57 zaps (Lightning) · Cashu NIP-87/60/61 |
| Rendering | local resolver → `localhost`; clearweb via njump |

**Genuinely new surface is only three things:** the unified node packaging +
user-controlled replication policy, the partial-seeding/mirroring logic plus the
Cashu incentive layer, and the templates. Everything else is *adopt the spec*.

## Node architecture

One daemon, four independent processes — run together (default) or each alone:

- **event-store** — a minimal Nostr relay (WebSocket + filter queries over SQLite)
- **blob-store** — a minimal Blossom server (PUT/GET/HEAD/list by sha256)
- **gateway / resolver** — turns a pubkey + identifier into a rendered site; owns
  no state, it's a pure projection
- **transport** — Direct or Tor (SOCKS out, optional `.onion` in)

A **replication controller** (P3) reads your policy and drives the two stores —
mirroring chosen sites, enforcing storage caps with file-level partial seeding,
and honoring bandwidth budgets.

## Principles

- **Interoperate with mainline Nostr; never fork the protocol.** Sanity-check
  every feature against: *does vanilla Nostr software still understand this?*
- **Assemble, don't invent.** The application layer already exists as NIPs.
- **Replication is user-controlled, not publisher-controlled.** You decide
  storage, bandwidth, which sites to seed, and privacy.
- **Honest persistence.** Content lives iff someone seeds it. Paid pinning
  (Cashu) is the escape valve for content lacking organic seeders.
- **Knowing, accountable operators.** No blind/encrypted-unknowable storage in
  v1. Moderation is layered and always *knowing*: an opt-in/opt-out base, npub
  allow/block lists, and per-item overrides — carry one piece you like even if its
  author isn't whitelisted, or is blacklisted (the latter with a warning). "I
  won't carry that," at any granularity.
- **House stack.** FastAPI + SQLite + vanilla JS. No npm, no build step,
  local-first. Templates are static + vanilla JS.

## Running it

Configuration is a single YAML policy file (schema in
[`SPEC.md` §4](./SPEC.md)); copy the example to start, then start the daemon:

```bash
pip install -r requirements.txt
cp policy.example.yaml policy.yaml

python -m pijn keygen                 # create your identity (encrypts the nsec; asks a passphrase)
python -m pijn run                    # start relay :4848, blob-store :4849, gateway :4850
```

All data lives under **`~/.pijn/<npub>/`** (relay db, blobs, state), so reinstalling
the code never touches it; set `PIJN_HOME` to relocate it. Your **nsec is stored
encrypted** (`~/.pijn/<npub>/nsec.enc`) and unlocked with your passphrase when a
signing command needs it — or set `PIJN_PASSPHRASE` for automation, or bypass with
a plaintext `PIJN_NSEC`. The **npub is plaintext** (public), so `pubkey` needs no
passphrase, and the **daemon runs unattended** — only `publish`/`post`/`blog`/
`announce` ask for the passphrase. `pijn identities` lists your keys (`--use` switches).

`keygen` is interactive: if an identity already exists it offers to keep it
(unlocking and verifying the key works) or overwrite it, and when making a new one
it asks whether to import an existing `nsec` (checked before it's saved) or generate
a fresh key. Use `keygen --force` to non-interactively overwrite with a new key.

### Addressing — root sites and named sites

Each identity (npub) can own **one root site** plus any number of **named
sites**, told apart by an identifier (a slug like `blog` or `notes`). Every site
is served from its own origin, so its links — relative *and* root-absolute like
`/style.css` — resolve to that site and nothing else:

| | canonical origin | also reachable at |
|---|---|---|
| **root site** | `http://<npub>.localhost:4850/` | `/n/<npub>/` (redirects here) |
| **named site** | `http://<id>.<npub>.localhost:4850/` | `http://localhost:4850/s/<npub>/<id>/` |

For **local** browsing, prefer the `<npub>.localhost` form for the root site and
the `/s/<npub>/<id>/` **path** form for named sites — the path form always works,
whereas the nested `<id>.<npub>.localhost` subdomain depends on your browser
resolving multi-level `.localhost` names (Chrome does; some setups don't). The
nested subdomain is the *canonical* address (it's what a clearweb gateway uses in
P5), but the path form is the dependable local route. Use `localhost`, not the
bare `127.0.0.1`.

> **One root manifest per identity.** A root site and a root blog occupy the
> *same* slot (both are kind-15128, keyed only by your pubkey), so publishing one
> replaces the other. If you want both a site **and** a blog under one key, make
> at least one of them a **named** site with `--identifier` (see below).

### Publish a static site

In another shell:

```bash
python -m pijn init mysite --title "My Site"     # scaffold a starter (relative links)
# edit mysite/*.html, then publish as your ROOT site:
python -m pijn publish mysite --title "My Site"
# -> browse: http://<npub>.localhost:4850/

# or publish the bundled demo (it uses root-absolute links, so view it via the subdomain):
python -m pijn publish examplesite --title "demo"
```

Re-running `publish` is the update path: a fresh manifest is signed and the old
one superseded — no blob is ever mutated. Use `--server <url>` to upload blobs to
an external Blossom host instead of this node.

### Publish a *named* site (a second site under the same key)

Give it an `--identifier`. It does **not** touch your root site:

```bash
python -m pijn init notes --title "Notes"
python -m pijn publish notes --identifier notes --title "Notes"
# -> browse locally: http://localhost:4850/s/<npub>/notes/
#    canonical:      http://notes.<npub>.localhost:4850/
```

### Publish a blog

A blog is long-form posts (NIP-23, kind 30023) **projected** into a site — the
gateway renders your posts on the fly and stores no HTML, and the same posts are
readable by any NIP-23 client (Habla, Yakihonne, …). Two steps: write posts with
`post`, and mark an origin as a blog **once** with `blog`.

Because of the one-root rule above, the common case is a **named** blog (so it
coexists with your root site):

```bash
python -m pijn init myblog --template blog --title "Field Notes"
python -m pijn post myblog/first-post.md --summary "Hello"   # signs a kind-30023 event
python -m pijn blog --title "Field Notes" --identifier blog  # mark a NAMED origin as a blog
# -> read it locally: http://localhost:4850/s/<npub>/blog/
#    each post at:     http://localhost:4850/s/<npub>/blog/<slug>
```

If instead you want the blog to **be** your main site, omit `--identifier` to make
it your root blog (this replaces any root static site):

```bash
python -m pijn blog --title "Field Notes"   # ROOT blog at http://<npub>.localhost:4850/
```

Editing a post and re-running `post` (same slug) supersedes the old version.

### Names

```bash
python -m pijn pubkey                 # print this node's npub
python -m pijn whois alice@example.com  # resolve & verify a NIP-05; or pass an npub for its digest
```

A claimed name is only ever shown beside a short, unfakeable npub digest, and a
NIP-05 is marked verified only after its domain actually vouches (SPEC §7).

### Seed someone else's site

This node can mirror other people's sites and keep them reachable when their
author is offline. List them under `sites:` in your policy (and point
`relays.read` at a relay that carries the author's events):

```yaml
relays:
  read: ["wss://relay.damus.io", "ws://127.0.0.1:4848"]
sites:
  - name: a-friends-blog
    pubkey: npub1...        # the author (npub or hex)
    identifier: blog        # "" = their root site; else a named site
    pin: true               # never evicted, ignore caps
  - name: someones-wiki
    pubkey: npub1...
    identifier: notes
    pin: false
    storage_cap: 500MB      # keep a subset up to this; evict the rest
```

```bash
python -m pijn sync          # mirror them now (prints a per-site report)
python -m pijn run           # also keeps them refreshed in the background
```

After a sync, this node serves each mirrored site from its own stores — so it
stays up even if the author's node goes down. Everything pulled is verified
before it's stored (signatures on events, sha256 on blobs), so the relays and
blob servers you pull from don't have to be trusted. `pin: true` keeps a full
copy; otherwise `storage_cap` keeps a subset of files (file-level partial
seeding) and `limits.storage_total` caps the whole node.

**Discovery.** You don't have to know the author's relay: the controller reads
their NIP-65 relay list (kind 10002) and pulls from the relays it names, so one
shared/indexer relay in `relays.read` is enough to find them. It also looks for
**other seeders** of the site (kind-30888 announcements) and will pull the
manifest and blobs from them too — so a site stays reachable even if the *author*
is offline, as long as someone seeds it. To make yourself discoverable as an
author and to advertise the sites you seed:

```bash
python -m pijn announce       # publishes your relay list + a seed announcement per seeded site
```

**Budgets.** `limits.storage_total` caps total disk; `limits.bandwidth_day` and
`bandwidth_month` cap how much replication downloads (metered across restarts).
When the node hits `storage_total`, `eviction.policy` decides what gives — default
`manual` (nothing auto-deleted; you prune), or `lru` to drop least-recently-stored
blobs; `protect_pinned: true` never evicts a pinned site's blobs.

### Running services separately

Each service can run alone (they bind separate ports):

```bash
python -m pijn run --only event_store   # just the relay
python -m pijn run --only blob_store     # just the Blossom server
python -m pijn run --only gateway        # just the resolver/renderer
```

Your `nsec` never enters the policy file or any server — it lives encrypted in
`~/.pijn/<npub>/nsec.enc`, is read only to sign, and is decrypted into memory only
when you run a signing command.

## Roadmap at a glance

`P0` spec → `P1` node skeleton (relay + Blossom + resolver) → `P2` publishing
tools + static/blog templates → `P3` replication & seeding → `P4` Tor →
`P5` clearweb bridge → `P6` forum → wiki → shop (+ Cashu, NIP-57 zaps) →
`P7` tipping authors/hosts, paid pinning, escrow, chunk-level swarm. Full detail
in [`roadmap.md`](./roadmap.md).

## Repository layout

```
pijn/
├── roadmap.md            # the plan
├── SPEC.md               # architecture spec (what's frozen)
├── README.md             # you are here
├── CHANGELOG.md          # what landed in each phase
├── requirements.txt      # pure-wheel deps; no build step
├── policy.example.yaml   # policy template (SPEC §4)
├── examplesite/          # a tiny static site for the publish demo
└── pijn/                 # the daemon package
    ├── __main__.py       # CLI: run/keygen/pubkey/identities/whois/init/publish/blog/post/sync/announce
    ├── app.py            # service composition + daemon runner
    ├── policy.py         # YAML policy loader (data paths under ~/.pijn/<npub>/)
    ├── keystore.py       # identity/data home; encrypted-key load/save
    ├── publish.py        # static-site publisher (content-typed blobs + manifest)
    ├── post.py           # blog authoring: kind-30023 posts + app=blog manifest
    ├── templates.py      # `init` scaffolds (static site, blog starter)
    ├── replication.py    # P3: mirror configured sites into the local stores
    ├── discovery.py      # P3: NIP-65 relay discovery + seeder announce/discovery
    ├── eviction.py       # P3: storage-cap eviction strategies (manual/lru/popularity)
    ├── bandwidth.py      # P3: persisted daily/monthly download budget
    ├── nostr/            # pure-Python core: schnorr, bech32, keys, events,
    │                     #   filters, nsite manifests, nip05, display, cipher
    │                     #   (ChaCha20-Poly1305 for the encrypted nsec)
    ├── event_store/      # SQLite persistence + NIP-01 WebSocket relay
    ├── blob_store/       # content-addressed storage + Blossom HTTP + 24242 auth
    ├── client/           # outbound relay (WS) + Blossom (HTTP) clients
    └── gateway/          # resolver + per-site-origin renderer; blog projection
                          #   (blog.py) and a safe Markdown subset (markdown.py)
```

`transport/` (Direct/Tor) arrives in P4. Active eviction, bandwidth budgets, and
seeder discovery finish P3 in 0.3.x.
