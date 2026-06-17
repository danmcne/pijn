# Changelog

All notable changes to pijn are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/); this project versions by
roadmap phase (see [`roadmap.md`](./roadmap.md)).

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
