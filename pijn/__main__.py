"""
pijn command-line interface.

    python -m pijn run      [--config policy.yaml] [--only event_store|blob_store|gateway]
    python -m pijn keygen   [--force]                # create/import an identity (nsec encrypted)
    python -m pijn pubkey                            # print the active npub (plaintext, no passphrase)
    python -m pijn identities [--use <npub>]         # list identities under ~/.pijn / switch active
    python -m pijn whois    <nip05-or-npub>          # resolve a name / show digest
    python -m pijn init     <dir> [--template static] [--title T]  # scaffold a site
    python -m pijn publish  <dir> [--identifier ID] [--title T] [--server URL] [--config policy.yaml]
    python -m pijn blog     [--title T] [--description D] [--identifier ID]  # mark origin as a blog
    python -m pijn post     <file.md> [--slug S] [--title T] [--summary D] [--tag X ...]  # kind 30023
    python -m pijn sync     [--config policy.yaml]    # mirror sites in policy into this node
    python -m pijn announce [--config policy.yaml]    # publish your NIP-65 relay list (discovery)

The daemon and the publisher both read the same policy file (default
`./policy.yaml`, falling back to built-in defaults if absent).
"""

import argparse
import asyncio
import getpass
import os

from . import app as node_app
from .nostr.keys import Keypair
from .policy import load_policy


def _cmd_run(args):
    policy = load_policy(args.config)
    node_app.run(policy, only=args.only)


def _verify_keypair(kp: Keypair) -> bool:
    """Confirm a key actually works: sign a random message and verify it."""
    from .nostr import schnorr

    try:
        msg = os.urandom(32)
        sig = schnorr.schnorr_sign(msg, kp.seckey_bytes)
        return schnorr.schnorr_verify(msg, bytes.fromhex(kp.pubkey_hex), sig)
    except Exception:
        return False


def _ask(prompt: str, default: str = "") -> str:
    try:
        return input(prompt).strip() or default
    except EOFError:
        return default


def _new_identity() -> Keypair | None:
    """Import an existing nsec or generate a fresh one; verify either way."""
    src = _ask("Import an existing nsec, or generate a new one? [i/g] (g): ", "g").lower()
    if src.startswith("i"):
        try:
            entered = getpass.getpass("Paste nsec (nsec1...): ").strip()
        except Exception:
            entered = ""
        try:
            kp = Keypair.from_nsec(entered)
        except Exception:
            print("That isn't a valid nsec — nothing was written.")
            return None
        if not _verify_keypair(kp):
            print("That key failed a sign/verify check — nothing was written.")
            return None
        print(f"Imported and verified {kp.npub}")
        return kp
    kp = Keypair.generate()
    print(f"Generated a new identity: {kp.npub}")
    return kp


def _new_password() -> str:
    """Prompt for a new passphrase (twice), or take PIJN_PASSPHRASE for automation."""
    env = os.environ.get("PIJN_PASSPHRASE")
    if env is not None:
        return env
    while True:
        p1 = getpass.getpass("Set a passphrase to encrypt your nsec: ")
        p2 = getpass.getpass("Confirm passphrase: ")
        if p1 and p1 == p2:
            return p1
        print("Passphrases didn't match (or were empty); try again.")


def _cmd_keygen(args):
    from . import keystore

    if args.force:  # non-interactive: overwrite the active identity with a fresh key
        kp = Keypair.generate()
        keystore.save_identity(kp, _new_password())
        print(f"saved new encrypted identity under {keystore.identity_dir(kp.npub)}\nnpub: {kp.npub}")
        return

    existing = keystore.active_npub()
    if existing and keystore.has_encrypted_key(existing):
        print(f"An identity already exists: {existing}")
        if _ask("Keep it, or overwrite? [k/o] (k): ", "k").lower().startswith("k"):
            pw = os.environ.get("PIJN_PASSPHRASE")
            if pw is None:
                pw = getpass.getpass(f"Passphrase to verify {existing[:12]}…: ")
            try:
                kp = keystore.load_keypair(existing, pw)
            except Exception:
                print("Couldn't unlock that key (wrong passphrase or corrupt file). "
                      "Run keygen again and choose overwrite to make a new one.")
                return
            if _verify_keypair(kp):
                print(f"Verified working — using {existing}")
            else:
                print("This key FAILED a sign/verify check; it does not work. "
                      "Run keygen again and choose overwrite to create a new one.")
            return
        # fall through to create a new identity (overwrite the active pointer)

    kp = _new_identity()
    if kp is not None:
        keystore.save_identity(kp, _new_password())
        print(f"saved encrypted identity under {keystore.identity_dir(kp.npub)}\nnpub: {kp.npub}")


def _cmd_pubkey(args):
    from . import keystore

    npub = keystore.active_npub()
    if not npub:
        raise SystemExit("no identity; run `pijn keygen` first")
    print(npub)  # public, read from plaintext — no passphrase needed


def _cmd_identities(args):
    from . import keystore

    active = keystore.active_npub()
    ids = keystore.list_identities()
    if not ids:
        print(f"no identities under {keystore.pijn_home()} (run `pijn keygen`)")
        return
    if args.use:
        if args.use not in ids:
            raise SystemExit(f"{args.use} is not a known identity")
        keystore.set_active(args.use)
        print(f"active identity is now {args.use}")
        return
    for npub in ids:
        print(("* " if npub == active else "  ") + npub)


def _cmd_whois(args):
    """Resolve a NIP-05 (or just show an npub's digest) the way a UI would.

    Demonstrates the naming model: a claimed name is only ever shown next to the
    npub digest, and a NIP-05 gets a ✓ only after the domain actually vouches.
    """
    from .nostr import display_name, name_badge, resolve_nip05, short_npub
    from .nostr.bech32 import normalize_pubkey

    ident = args.identity.strip()
    if ident.startswith("npub1") or len(ident) == 64:
        # Bare key: no name to verify, just the digest (the unfakeable part).
        print(name_badge(ident))
        return

    resolved = asyncio.run(resolve_nip05(ident))
    if resolved is None:
        print(f"{ident}: NIP-05 did not resolve (domain did not vouch)")
        return
    npub = normalize_pubkey(resolved["pubkey"])
    print(name_badge(npub, claimed_name="", nip05=display_name(ident), nip05_verified=True))
    print(f"  pubkey: {short_npub(npub)}")
    if resolved["relays"]:
        print(f"  relay hints (outbox): {', '.join(resolved['relays'])}")


def _cmd_publish(args):
    from .publish import publish_site

    policy = load_policy(args.config)
    keypair = policy.load_keypair()
    blossom_url = args.server or policy.blossom_public_url
    summary = asyncio.run(publish_site(
        directory=args.directory,
        keypair=keypair,
        blossom_url=blossom_url,
        relay_url=policy.relay_public_url,
        identifier=args.identifier,
        title=args.title,
    ))
    gw = policy.gateway
    npub = summary["npub"]
    # Canonical per-site origin: <id>.<npub>.<host> for named, <npub>.<host> for root.
    sub = f"{summary['identifier']}.{npub}" if summary["identifier"] else npub
    print(f"published {summary['files']} file(s) as kind {summary['kind']}")
    print(f"manifest: {summary['manifest_id']}")
    print(f"browse:   http://{sub}.localhost:{gw.port}/")


def _cmd_init(args):
    """Scaffold a starter site the author edits, then publishes with `publish`."""
    from .templates import scaffold

    created = scaffold(args.directory, kind=args.template, title=args.title)
    print(f"created {args.template} template in {args.directory}/")
    for path in created:
        print(f"  {path}")
    if args.template == "blog":
        print(f"\nedit the post, then from {args.directory}/:")
        print(f"  python -m pijn post first-post.md")
        print(f"  python -m pijn blog --title \"{args.title}\""
              + (f" --identifier {args.identifier}" if args.identifier else ""))
    else:
        print(f"\nedit it, then: python -m pijn publish {args.directory}"
              + (f" --identifier {args.identifier}" if args.identifier else ""))


def _cmd_blog(args):
    from .post import publish_blog

    policy = load_policy(args.config)
    keypair = policy.load_keypair()
    summary = asyncio.run(publish_blog(
        keypair=keypair, relay_url=policy.relay_public_url,
        title=args.title, description=args.description, identifier=args.identifier,
    ))
    gw = policy.gateway
    npub = summary["npub"]
    sub = f"{summary['identifier']}.{npub}" if summary["identifier"] else npub
    print(f"blog manifest published (kind {summary['kind']})")
    print(f"posts published with `post` will appear at:")
    print(f"  http://{sub}.localhost:{gw.port}/")


def _cmd_post(args):
    from .post import publish_post

    policy = load_policy(args.config)
    keypair = policy.load_keypair()
    summary = asyncio.run(publish_post(
        path=args.file, keypair=keypair, relay_url=policy.relay_public_url,
        slug=args.slug, title=args.title, summary=args.summary, tags=args.tag or [],
    ))
    print(f"published post '{summary['title']}' (slug: {summary['slug']})")
    print(f"event id: {summary['id']}")
    print("readable by any NIP-23 client; visible in your blog once `blog` is published")


def _cmd_sync(args):
    """One-shot: mirror every configured site into this node's stores now."""
    from .event_store import EventStore
    from .blob_store import BlobStore
    from .replication import ReplicationController

    policy = load_policy(args.config)
    if not policy.sites:
        print("no sites configured under `sites:` in the policy")
        return
    os.makedirs(policy.data_dir, exist_ok=True)
    store = EventStore(policy.event_store.db)
    blobs = BlobStore(policy.blob_store.path)
    from .bandwidth import BandwidthMeter
    meter = BandwidthMeter(
        os.path.join(policy.state_dir, "bandwidth.json"),
        day_cap=policy.bandwidth_day, month_cap=policy.bandwidth_month,
    )
    controller = ReplicationController(
        store=store, blob_store=blobs, sites=policy.sites,
        source_relays=policy.relays_read or [policy.relay_public_url],
        default_blossom=policy.blossom_servers or [policy.blossom_public_url],
        storage_total=policy.storage_total, eviction=policy.eviction, meter=meter,
    )
    reports = asyncio.run(controller.sync_all())
    store.close()
    for r in reports:
        loc = f"/{r['identifier']}" if r["identifier"] else ""
        where = f"{r['name']} ({r['pubkey']}…{loc})"
        if r["manifest"] == "not found":
            print(f"  {where}: manifest not found on source relays")
            continue
        extra = []
        if r["relays_discovered"]:
            extra.append(f"+{r['relays_discovered']} relay(s)")
        if r["seeders"]:
            extra.append(f"{r['seeders']} seeder(s)")
        line = (f"  {where}: {r['files_fetched']} fetched, {r['files_present']} present, "
                f"{r['files_skipped']} skipped, {r['bytes']} bytes")
        if r["posts"]:
            line += f", {r['posts']} posts"
        if r["missing"]:
            line += f", MISSING {len(r['missing'])}"
        if extra:
            line += " [" + ", ".join(extra) + "]"
        print(line)


def _cmd_announce(args):
    """Publish this node's NIP-65 relay list and a seed announcement per seeded site."""
    from .discovery import build_relay_list_event, build_seed_announcement
    from .nostr.nsite import KIND_NAMED, KIND_ROOT
    from .client.relay_client import RelayClient

    policy = load_policy(args.config)
    kp = policy.load_keypair()
    targets = policy.relays_write or [policy.relay_public_url]

    events = [("relay list (kind 10002)",
               build_relay_list_event(policy.relays_read, policy.relays_write)
               .sign(kp.seckey_bytes))]
    # Advertise the sites this node hosts (seed: true), pointing at its own
    # blob server + relay so others can discover and pull from this seeder.
    my_servers = [policy.blossom_public_url]
    my_relays = policy.relays_write or [policy.relay_public_url]
    for site in policy.sites:
        if not site.seed:
            continue
        kind = KIND_NAMED if site.identifier else KIND_ROOT
        ev = build_seed_announcement(kind, site.pubkey, site.identifier,
                                     my_servers, my_relays).sign(kp.seckey_bytes)
        events.append((f"seed: {site.name}", ev))

    async def _go():
        out = []
        for label, ev in events:
            results = []
            for url in targets:
                try:
                    ok, msg = await RelayClient(url).publish(ev)
                except Exception as e:
                    ok, msg = False, str(e)
                results.append((url, ok))
            out.append((label, results))
        return out

    print(f"announced as {kp.npub}")
    for label, results in asyncio.run(_go()):
        oks = sum(1 for _u, ok in results if ok)
        print(f"  {label}: {oks}/{len(results)} relays ok")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="pijn")
    parser.add_argument("--config", default="policy.yaml", help="policy YAML path")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="run the node daemon")
    p_run.add_argument("--only", choices=["event_store", "blob_store", "gateway"])
    p_run.set_defaults(func=_cmd_run)

    p_keygen = sub.add_parser("keygen", help="generate and save a keypair")
    p_keygen.add_argument("--force", action="store_true")
    p_keygen.set_defaults(func=_cmd_keygen)

    p_pubkey = sub.add_parser("pubkey", help="print this node's npub")
    p_pubkey.set_defaults(func=_cmd_pubkey)

    p_ids = sub.add_parser("identities", help="list identities under ~/.pijn (or switch with --use)")
    p_ids.add_argument("--use", default="", help="set the active identity to this npub")
    p_ids.set_defaults(func=_cmd_identities)

    p_whois = sub.add_parser("whois", help="resolve a NIP-05 name or show an npub digest")
    p_whois.add_argument("identity", help="a NIP-05 (alice@example.com) or an npub/hex pubkey")
    p_whois.set_defaults(func=_cmd_whois)

    p_init = sub.add_parser("init", help="scaffold a starter site to edit and publish")
    p_init.add_argument("directory")
    p_init.add_argument("--template", default="static", choices=["static", "blog"],
                        help="which starter to scaffold")
    p_init.add_argument("--title", default="My pijn site")
    p_init.add_argument("--identifier", default="", help="named-site id this is meant for")
    p_init.set_defaults(func=_cmd_init)

    p_pub = sub.add_parser("publish", help="publish a directory as a site")
    p_pub.add_argument("directory")
    p_pub.add_argument("--identifier", default="", help="named-site id (omit for root site)")
    p_pub.add_argument("--server", default="", help="Blossom URL to upload blobs to (default: this node)")
    p_pub.add_argument("--title", default="")
    p_pub.set_defaults(func=_cmd_publish)

    p_blog = sub.add_parser("blog", help="mark this identity's origin as a blog")
    p_blog.add_argument("--title", default="")
    p_blog.add_argument("--description", default="")
    p_blog.add_argument("--identifier", default="", help="named-site id (omit for root blog)")
    p_blog.set_defaults(func=_cmd_blog)

    p_post = sub.add_parser("post", help="publish a Markdown file as a long-form post (kind 30023)")
    p_post.add_argument("file")
    p_post.add_argument("--slug", default="", help="URL slug / d-tag (default: from filename)")
    p_post.add_argument("--title", default="", help="default: first # heading or filename")
    p_post.add_argument("--summary", default="")
    p_post.add_argument("--tag", action="append", help="topic tag (repeatable)")
    p_post.set_defaults(func=_cmd_post)

    p_sync = sub.add_parser("sync", help="mirror the sites in your policy into this node now")
    p_sync.set_defaults(func=_cmd_sync)

    p_announce = sub.add_parser("announce", help="publish your NIP-65 relay list (kind 10002)")
    p_announce.set_defaults(func=_cmd_announce)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (FileNotFoundError, ValueError) as e:
        raise SystemExit(f"error: {e}")


if __name__ == "__main__":
    main()
