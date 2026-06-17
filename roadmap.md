# pijn — project roadmap

pijn is a self-hostable decentralized web where identities own signed content,
users choose how much of the network they support, and a "website" is just one
way of rendering that content. Built **on** Nostr, not beside it.

---

## Guiding principles

- **Interoperate with mainline Nostr; never fork the protocol.** Every layer
  uses real, published NIPs, so existing relays, Blossom servers, clients, and
  gateways work with our content immediately. This is the answer to the
  cold-start problem that killed ZeroNet/OpenBazaar/etc. — we join a populated
  network instead of seeding an empty one. Sanity check every feature against:
  *does vanilla Nostr software still understand this?*
- **Assemble, don't invent.** The application layer already exists as NIPs (see
  below). New protocol surface should be near zero.
- **Replication is user-controlled, not publisher-controlled.** Each participant
  decides storage, bandwidth, which sites to seed, and privacy — per the YAML
  policy.
- **Honest persistence model.** Content survives iff someone chooses to seed it
  (the torrent model). "Censorship resistance" means *takedown-resistance for
  content people value*, not blanket availability. Paid pinning (Cashu) is the
  escape valve for content lacking organic seeders.
- **Separable services.** Event-store, blob-store, client/gateway, and transport
  are independent processes. The default install runs them together; any can run
  alone.
- **House stack.** FastAPI + SQLite + vanilla JS. No npm, no build step,
  local-first. Templates are static + vanilla JS.

---

## What already exists (adopt, don't build)

| Capability | Mechanism | Status |
|---|---|---|
| Identity, signatures | Nostr pubkeys / events | adopt |
| Mutable pubkey-addressed sites | nsite (NIP-5A, kind 35128) | adopt spec |
| Immutable media/files | Blossom (sha256 blobs) | adopt spec |
| Blog | Long-form, kind 30023 | adopt |
| Wiki (with versioning + fork/merge + WoT) | NIP-54, kind 30818 | adopt |
| Forum / community | NIP-72, kind 34550 | adopt |
| Shop | NIP-15, kinds 30017/30018 | adopt |
| Shop payments | Cashu (NIP-87 mint announce, NIP-69 orders) | adopt + integrate |
| Tipping / zaps | NIP-57 (Lightning zaps) + Cashu | adopt + integrate |
| Git repos | NIP-34 | optional |
| Clearweb bridge + SEO | njump (server-rendered, indexable) | adopt/fork |
| Publishing CLI reference | nsyte | reference |

**Genuinely new surface = 3 things only:** (1) the unified node packaging +
user-controlled replication policy; (2) partial-seeding/mirroring logic + the
Cashu incentive layer; (3) the templates.

---

## v1 scope decisions (locked)

- **Immutable layer:** Blossom, whole-blob. **File-level** partial seeding only.
- **Transport:** Direct + Tor. (I2P/Lokinet deferred but pluggable.)
- **App types shipping first:** static site + blog. Wiki/forum/shop follow.
- **No blind storage in v1.** Blind/encrypted-unknowable storage doesn't map onto
  plaintext Blossom/relays, and conflicts with the "knowing, accountable
  operator" stance. Keep opt-in / opt-out (both knowing). Revisit only on real
  demand, as a separate encrypted-store module.
- **No chunk-level swarm / DHT in v1.** Deferred until large media forces it.

---

## Phases

### P0 — Spec & decisions (no code)
- **Goal:** freeze the architecture before building.
- **Deliverables:** layer spec with each layer pinned to its NIP/component;
  node service boundaries; the replication-policy schema; the data model
  (what is an *event* — manifest/pointer/revision — vs what is a *blob* — bytes).
- **Exit:** a 2–3 page spec your colleague signs off on.

### P1 — Node skeleton (the daemon)
- **Goal:** a local daemon bundling the three core services, runnable together or
  separately.
- **Build:** minimal Nostr relay (websocket + filter queries over SQLite);
  minimal Blossom server (PUT/GET/HEAD/list by sha256, Nostr-signed auth);
  local resolver/gateway that renders a site to the browser at `localhost`.
  Config loader for the YAML policy.
- **Exit:** publish your own static site and browse it locally in Firefox.
- **Decision:** build the relay in Python (control + stack fit) vs adopt a
  hardened relay (strfry/khatru) for public nodes later. *Recommend build for
  v1, keep the option open.*

### P2 — Publishing tools + first templates
- **Goal:** author → publish → update, from a template.
- **Build:** a publisher (dir of files → blobs to Blossom → nsite manifest
  events → relays; mutable updates via re-signing). Static-site template + blog
  template (kind 30023).
- **Exit:** a non-trivial site published from a template, editable in place,
  visible to a vanilla Nostr client as proof of interop.

### P3 — Replication & seeding
- **Goal:** the user-controlled replication policy, for real.
- **Build:** mirror selected sites (pull manifest + blobs); enforce per-site
  storage caps with file-level partial seeding (keep a subset; evict by
  recency/popularity); bandwidth budget; `pin` / `seed: false` semantics. Find
  other seeders/relays holding a site.
- **Exit:** a site stays reachable while its author is offline because others
  seed it.

### P4 — Transport & privacy
- **Goal:** Tor as a first-class, visible control.
- **Build:** route outbound relay/blob connections through Tor (SOCKS); expose
  the node's relay/blob/gateway as a `.onion` hidden service (optional, inbound);
  per-site Direct/Tor toggle in the UI, with the slowness warning.
- **Exit:** one-click anonymous browse + publish. Many relays are already
  `.onion`, so most of this composes for free.

### P5 — Clearweb bridge
- **Goal:** sites findable on the normal web + search engines.
- **Build/adopt:** a public HTTP gateway on a clearnet domain that
  server-renders sites (start by adopting/forking njump for SEO correctness;
  build a FastAPI+Jinja one later for stack consistency). Sitemaps generated
  from manifests.
- **Exit:** a published site is Google-indexable and viewable with no install.

### P6 — More app types
- **Goal:** the full set, all over one identity.
- **Order:** forum first (reddit/usenet-style threaded community — the app type
  vanilla Nostr actually lacks; short "post" notes and standalone "pages" are
  already covered by kind-1 microblogging and the static-site template). Then
  wiki, then shop.
- **Build:** forum template/renderer (NIP-72 reddit-style vs NIP-7D usenet/threads
  — decide at entry; NIP-29 groups are a different, chat-shaped thing); wiki
  template/renderer (NIP-54); shop (NIP-15) with **Cashu** payment integration
  (città nostr work plugs in here). Surface author tipping in templates via NIP-57
  zaps (+ Cashu).
- **Exit:** forum, wiki, shop, blog, and general site all publishable as
  templates from the same pubkey.

### P7 — Incentives & hard problems (research / later)
- **Value to authors *and* hosts.** One reader action sends value to either the
  **author** or the **relay/blob host seeding** content they value. Author zaps
  are vanilla NIP-57 (Lightning); routing value to the *seeder* is the new surface
  and shares plumbing with paid pinning below. (Could land in P6 if template-only;
  the host-side flow is what pushes it here.)
- Cashu-**paid pinning**: pay a seeder to keep your content alive.
- Shop **trust/escrow/reputation** via Nostr web-of-trust — the genuinely
  unsolved part (what sank OpenBazaar). Cashu gives private payment, not escrow.
- **Chunk-level swarm + DHT** if/when large media demands sub-file partial
  seeding (reference real torrents/Hypercore from the manifest rather than
  chunk-ifying everything).
- Optional: I2P/Lokinet transports (drop-in via the transport abstraction).

---

## Cross-cutting concerns (every phase)

- **Key management.** The user's `nsec` is the crown jewel — local-only signing,
  never exposed to the gateway or any server, optional separate signing device.
- **Naming / identity.** NIP-05 for human-readable names; web-of-trust for
  ranking and anti-impersonation.
- **Search / discovery within the network.** Beyond direct links — relay-side
  search (NIP-50), curated indexes, WoT-based ranking.
- **Moderation.** Per-relay/per-Blossom policy with npub allow/block lists *and*
  per-content overrides: opt in to a specific item even when its author isn't
  whitelisted — or is blacklisted, the latter with a warning. This is what
  opt-in/opt-out *is*; honor the "I won't carry that" model at any granularity.
- **Packaging / distribution.** How a non-technical user installs and runs the
  node (single binary? container? OS service?).
- **Interop tests.** A standing check that vanilla Nostr clients/relays/gateways
  still read our content.

---

## Resolved decisions (locked)

1. **Relay: build in Python for v1** — but with inputs/outputs consistent with a
   standard relay, so a hardened relay (strfry/khatru) can drop in for public
   nodes later without changing callers.
2. **Public clearweb gateway: adopt njump.**
3. **First app type after static + blog: forum** — reddit/usenet-style threaded
   community, ahead of wiki and shop. (Short "post" notes and standalone "pages"
   already exist via kind-1 + the static-site template.) *Which* forum NIP —
   NIP-72 (reddit-style) vs NIP-7D (usenet/threads) — is decided at P6 entry.
4. **P7 timing: as planned**, with one addition pulled to the top of P7 (or P6 if
   it turns out template-only): unified tipping that sends value to authors *or*
   the hosts/seeders of content one values (NIP-57 zaps + Cashu).
