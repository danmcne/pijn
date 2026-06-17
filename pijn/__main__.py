"""
pijn command-line interface.

    python -m pijn run      [--config policy.yaml] [--only event_store|blob_store|gateway]
    python -m pijn keygen   [--config policy.yaml]   # create + save a keypair
    python -m pijn pubkey   [--config policy.yaml]   # print this node's npub
    python -m pijn whois    <nip05-or-npub>          # resolve a name / show digest
    python -m pijn init     <dir> [--template static] [--title T]  # scaffold a site
    python -m pijn publish  <dir> [--identifier ID] [--title T] [--server URL] [--config policy.yaml]
    python -m pijn blog     [--title T] [--description D] [--identifier ID]  # mark origin as a blog
    python -m pijn post     <file.md> [--slug S] [--title T] [--summary D] [--tag X ...]  # kind 30023

The daemon and the publisher both read the same policy file (default
`./policy.yaml`, falling back to built-in defaults if absent).
"""

import argparse
import asyncio
import os

from . import app as node_app
from .nostr.keys import Keypair
from .policy import load_policy


def _cmd_run(args):
    policy = load_policy(args.config)
    node_app.run(policy, only=args.only)


def _cmd_keygen(args):
    policy = load_policy(args.config)
    if os.path.exists(policy.nsec_file) and not args.force:
        raise SystemExit(f"{policy.nsec_file} exists; pass --force to overwrite")
    kp = Keypair.generate()
    os.makedirs(os.path.dirname(policy.nsec_file) or ".", exist_ok=True)
    with open(policy.nsec_file, "w") as f:
        f.write(kp.nsec + "\n")
    os.chmod(policy.nsec_file, 0o600)  # the nsec is the crown jewel
    print(f"saved secret key to {policy.nsec_file} (chmod 600)")
    print(f"npub: {kp.npub}")


def _cmd_pubkey(args):
    policy = load_policy(args.config)
    print(policy.load_keypair().npub)


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

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
