# pijn

**A self-hostable decentralized web where identities own signed content, users
choose how much of the network they support, and a "website" is just one way of
rendering that content.** Built *on* Nostr, not beside it.

> **Status:** P2 (v0.2.1) — P2 exit met. Each site is served from its own origin
> (`<npub>.<host>` / `<id>.<npub>.<host>`); a templated publisher (`init` /
> `publish`) ships a `static` starter; and a **blog** projects kind-30023
> long-form posts (`post` / `blog`) into a rendered site that any NIP-23 client
> can also read. Naming primitives (NIP-05 + npub digest) landed in v0.1.2.
> The three core services (relay,
> Blossom blob-store, gateway) build and run, and you can publish a static site
> and browse it locally. See [`SPEC.md`](./SPEC.md) for the frozen architecture,
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

P1 ships a working daemon. Configuration is a single YAML policy file (schema in
[`SPEC.md` §4](./SPEC.md)); copy the example to start:

```bash
pip install -r requirements.txt
cp policy.example.yaml policy.yaml

python -m pijn keygen                 # create your identity (writes ./.pijn/nsec, chmod 600)
python -m pijn run                    # start relay :4848, blob-store :4849, gateway :4850
```

In another shell, publish a static site and browse it:

```bash
python -m pijn publish examplesite --title "demo"
# -> prints a browse URL like http://127.0.0.1:4850/n/<npub>/
```

Open that URL in Firefox — the page is a content-addressed blob whose manifest is
a signed Nostr event owned by your key. Because every service speaks plain
NIP-01 / Blossom, the manifest is also readable by any vanilla Nostr client.

Each service can run alone (they bind separate ports):

```bash
python -m pijn run --only event_store   # just the relay
python -m pijn run --only blob_store     # just the Blossom server
python -m pijn run --only gateway        # just the resolver/renderer
```

Your `nsec` never enters the policy file or any server — it is read only from
`./.pijn/nsec` or the `PIJN_NSEC` environment variable, and only to sign.

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
    ├── __main__.py       # CLI: run / keygen / pubkey / publish
    ├── app.py            # service composition + daemon runner
    ├── policy.py         # YAML policy loader
    ├── publish.py        # minimal site publisher (P2 adds templates)
    ├── nostr/            # pure-Python core: schnorr, bech32, keys, events,
    │                     #   filters, nsite manifests — no native crypto dep
    ├── event_store/      # SQLite persistence + NIP-01 WebSocket relay
    ├── blob_store/       # content-addressed storage + Blossom HTTP + 24242 auth
    ├── client/           # outbound relay (WS) + Blossom (HTTP) clients
    └── gateway/          # resolver (local/remote sources) + local renderer
```

`transport/` (Direct/Tor) and `templates/` arrive in later phases (P4, P2).
