"""
Local gateway / renderer.

Each site is served from its own *origin* (subdomain), so that a site's
root-absolute links (`<link href="/style.css">`) resolve to that site and
nothing else:

    http://<npub>.<host>/<path...>              a pubkey's ROOT site
    http://<identifier>.<npub>.<host>/<path...>  a pubkey's NAMED site

Why subdomains and not a path prefix: under `/n/<npub>/…` the browser requests
`/style.css` at the gateway root, with no npub attached, so the gateway can't
tell which site it belongs to — the page renders unstyled and absolute links
404. An origin per site removes the ambiguity. Browsers resolve `*.localhost`
to 127.0.0.1 with no setup, so this works out of the box locally and maps
straight onto a wildcard clearweb domain in P5.

The legacy path routes (`/n/…`, `/s/…`) are kept only as redirectors to the
canonical subdomain, so an old or hand-typed link still lands on the working
URL. The gateway holds no state; it just drives the resolver.

`<npub>` may be a bech32 npub or 64-char hex pubkey, but note a 64-char hex
pubkey exceeds the 63-char DNS label limit — the canonical subdomain always uses
the npub form, which fits exactly.
"""

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from ..nostr.bech32 import normalize_pubkey, to_npub

_LANDING = """<!doctype html><meta charset=utf-8>
<title>pijn gateway</title>
<body style="font-family:system-ui;max-width:40rem;margin:3rem auto;padding:0 1rem">
<h1>pijn gateway</h1>
<p>This node renders sites owned by Nostr identities.</p>
<p>Open a root site at <code>http://&lt;npub&gt;.localhost:4850/</code>, or a named
site at <code>http://&lt;identifier&gt;.&lt;npub&gt;.localhost:4850/</code>. Both
relative and root-absolute links work, because each site has its own origin.</p>
<p>The old <code>/n/&lt;npub&gt;/</code> and <code>/s/&lt;npub&gt;/&lt;id&gt;/</code>
links still work — they redirect to the address above.</p>
</body>"""


def _label_pubkey(label: str):
    """Return the hex pubkey if `label` is an npub/hex, else None."""
    try:
        return normalize_pubkey(label)
    except ValueError:
        return None


def _security_headers(generated: bool) -> dict:
    """Baseline hardening headers for everything the gateway serves.

    `nosniff` stops a non-HTML blob being re-interpreted as HTML; the others
    blunt clickjacking and referrer leakage. For pijn-*generated* HTML (blog
    pages) we can also impose a strict CSP that forbids scripts outright —
    defence-in-depth behind the Markdown sanitizer. We do *not* impose a
    script CSP on raw author blobs, since legitimate static sites ship their
    own JS; per-npub origin isolation is their boundary.
    """
    h = {
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }
    if generated:
        h["X-Frame-Options"] = "DENY"
        h["Content-Security-Policy"] = (
            "default-src 'none'; img-src * data: blob:; style-src 'unsafe-inline'; "
            "font-src *; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        )
    else:
        h["X-Frame-Options"] = "SAMEORIGIN"
    return h


def build_gateway_app(resolver) -> FastAPI:
    app = FastAPI(title="pijn gateway")
    app.state.resolver = resolver

    async def _render(pubkey: str, path: str, identifier: str):
        result = await resolver.resolve(pubkey, path, identifier)
        if result is None:
            return Response("not found", status_code=404)
        data, content_type, generated = result
        return Response(content=data, media_type=content_type,
                        headers=_security_headers(generated))

    @app.middleware("http")
    async def subdomain_router(request: Request, call_next):
        """Serve `<npub>.<host>` (root) and `<id>.<npub>.<host>` (named) sites.

        The pubkey may be the first label (root) or the second (named, with the
        identifier as the first label). We don't rely on label *count*, so this
        works under `*.localhost` and under a multi-label clearweb domain alike.
        """
        labels = request.headers.get("host", "").split(":")[0].split(".")
        if labels:
            pk0 = _label_pubkey(labels[0])
            if pk0 is not None:
                return await _render(pk0, request.url.path, "")
            if len(labels) >= 2:
                pk1 = _label_pubkey(labels[1])
                if pk1 is not None:
                    return await _render(pk1, request.url.path, labels[0])
        return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    async def landing():
        return HTMLResponse(_LANDING, headers=_security_headers(generated=True))

    # --- legacy path scheme: redirect to the canonical per-site origin ---------

    def _redirect(npub: str, identifier: str, path: str, request: Request):
        pubkey = _label_pubkey(npub)
        if pubkey is None:
            return Response("invalid npub", status_code=400)
        name, _, port = request.headers.get("host", "").partition(":")
        # A bare IP can't carry a subdomain; localhost's subdomains resolve to
        # 127.0.0.1 anyway, so redirect IP hosts there instead.
        if name and all(c.isdigit() or c == "." for c in name):
            name = "localhost"
        host = f"{name}:{port}" if port else name
        sub = f"{identifier}.{to_npub(pubkey)}" if identifier else to_npub(pubkey)
        tail = path if path.startswith("/") else "/" + path
        return RedirectResponse(f"{request.url.scheme}://{sub}.{host}{tail}", status_code=307)

    @app.get("/n/{npub}")
    async def root_index(npub: str, request: Request):
        return _redirect(npub, "", "/", request)

    @app.get("/n/{npub}/{path:path}")
    async def root_path(npub: str, path: str, request: Request):
        return _redirect(npub, "", path, request)

    # Named sites are *served* here, not redirected: their canonical origin is
    # the nested `<id>.<npub>.<host>`, but nested `.localhost` doesn't resolve
    # reliably in every browser, so the path form is the dependable local route.
    # The gateway renders blogs (and relative-link sites) with relative links,
    # which resolve correctly under this prefix.
    @app.get("/s/{npub}/{identifier}")
    async def named_index(npub: str, identifier: str, request: Request):
        # Add the trailing slash so the page's relative links keep the prefix.
        return RedirectResponse(request.url.path + "/", status_code=307)

    @app.get("/s/{npub}/{identifier}/{path:path}")
    async def named_path(npub: str, identifier: str, path: str, request: Request):
        pubkey = _label_pubkey(npub)
        if pubkey is None:
            return Response("invalid npub", status_code=400)
        return await _render(pubkey, "/" + path, identifier)

    return app
