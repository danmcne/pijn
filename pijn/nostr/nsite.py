"""
nsite manifests (NIP-5A).

A "site" is a manifest event mapping absolute request paths to blob hashes:

    root site   -> kind 15128 (replaceable; one per pubkey)
    named site  -> kind 35128 (addressable; `d` tag = identifier)

Manifest tags:
    ["path", "/index.html", "<sha256>"]   one per file (required)
    ["server", "<blossom url>"]           hint(s): where to find the blobs
    ["title", ...] ["description", ...]    optional metadata
    ["source", "<url>"]                    optional link to source

This module is the single place that knows the manifest shape, so the publisher
and the gateway resolver can never drift apart.

`KIND_ROOT` / `KIND_NAMED` correspond to SPEC delta D1 (15128 root, 35128 named;
34128 is the deprecated legacy kind we read for back-compat only).
"""

import posixpath

from .event import make_event

KIND_ROOT = 15128
KIND_NAMED = 35128
KIND_LEGACY = 34128  # deprecated; resolver reads it, publisher never writes it


def build_manifest(paths: dict, servers: list, identifier: str = "",
                   title: str = "", description: str = "", source: str = ""):
    """Build an *unsigned* manifest event. `paths` maps abs path -> sha256 hex."""
    tags = []
    if identifier:
        tags.append(["d", identifier])
    if title:
        tags.append(["title", title])
    if description:
        tags.append(["description", description])
    if source:
        tags.append(["source", source])
    for server in servers:
        tags.append(["server", server])
    for path, sha in sorted(paths.items()):
        tags.append(["path", path, sha])

    kind = KIND_NAMED if identifier else KIND_ROOT
    return make_event(kind=kind, content="", tags=tags)


def parse_manifest(event) -> dict:
    """Extract a manifest into {paths, servers, title, description, identifier}."""
    paths = {}
    for t in event.tags:
        if t and t[0] == "path" and len(t) >= 3:
            paths[t[1]] = t[2]
    return {
        "paths": paths,
        "servers": event.tag_values("server"),
        "title": event.first_tag("title") or "",
        "description": event.first_tag("description") or "",
        "identifier": event.d_tag,
    }


def normalize_request_path(path: str) -> str:
    """Map an incoming URL path to a manifest key.

    Ensures a leading slash, collapses '..', and turns a directory-style path
    (ending in '/' or with no extension) into its '/index.html'.
    """
    if not path.startswith("/"):
        path = "/" + path
    path = posixpath.normpath(path)
    if path == "/" or path.endswith("/"):
        return posixpath.join(path, "index.html").replace("//", "/")
    # No file extension -> treat as a directory and serve its index.
    if "." not in posixpath.basename(path):
        return posixpath.join(path, "index.html")
    return path


def resolve_blob(manifest: dict, request_path: str) -> str | None:
    """Return the sha256 for a request path, or None if the site lacks it."""
    key = normalize_request_path(request_path)
    if key in manifest["paths"]:
        return manifest["paths"][key]
    # Fall back to the literal path (e.g. an extensionless file that *was*
    # published under its exact name).
    literal = request_path if request_path.startswith("/") else "/" + request_path
    return manifest["paths"].get(literal)
