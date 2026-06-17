"""
pijn command-line interface.

    python -m pijn run      [--config policy.yaml] [--only event_store|blob_store|gateway]
    python -m pijn keygen   [--config policy.yaml]   # create + save a keypair
    python -m pijn pubkey   [--config policy.yaml]   # print this node's npub
    python -m pijn publish  <dir> [--identifier ID] [--title T] [--config policy.yaml]

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


def _cmd_publish(args):
    from .publish import publish_site

    policy = load_policy(args.config)
    keypair = policy.load_keypair()
    summary = asyncio.run(publish_site(
        directory=args.directory,
        keypair=keypair,
        blossom_url=policy.blossom_public_url,
        relay_url=policy.relay_public_url,
        identifier=args.identifier,
        title=args.title,
    ))
    site = f"/s/{summary['npub']}/{summary['identifier']}/" if summary["identifier"] \
        else f"/n/{summary['npub']}/"
    gw = policy.gateway
    print(f"published {summary['files']} file(s) as kind {summary['kind']}")
    print(f"manifest: {summary['manifest_id']}")
    print(f"browse:   http://{gw.host}:{gw.port}{site}")


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

    p_pub = sub.add_parser("publish", help="publish a directory as a site")
    p_pub.add_argument("directory")
    p_pub.add_argument("--identifier", default="", help="named-site id (omit for root site)")
    p_pub.add_argument("--title", default="")
    p_pub.set_defaults(func=_cmd_publish)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
