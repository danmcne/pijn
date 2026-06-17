"""
Local gateway / renderer.

Serves resolved sites to a normal browser at `localhost`:

    GET /n/<npub>/<path...>              a pubkey's ROOT site
    GET /s/<npub>/<identifier>/<path...> a pubkey's NAMED site
    GET /                                a tiny landing page

`<npub>` may be a bech32 npub or a 64-char hex pubkey. The gateway holds no
state; it just drives the resolver. This is the piece that satisfies the P1
exit: publish your own static site and browse it locally in Firefox.
"""

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse

from ..nostr.bech32 import normalize_pubkey

_LANDING = """<!doctype html><meta charset=utf-8>
<title>pijn gateway</title>
<body style="font-family:system-ui;max-width:40rem;margin:3rem auto;padding:0 1rem">
<h1>pijn gateway</h1>
<p>This node renders sites owned by Nostr identities.</p>
<p>Open a root site at <code>http://&lt;npub&gt;.localhost:4850/</code> (recommended —
relative <em>and</em> root-absolute links work), or via the path scheme at
<code>/n/&lt;npub&gt;/</code>. Named sites: <code>/s/&lt;npub&gt;/&lt;identifier&gt;/</code>.</p>
</body>"""


def build_gateway_app(resolver) -> FastAPI:
    app = FastAPI(title="pijn gateway")
    app.state.resolver = resolver

    @app.middleware("http")
    async def subdomain_router(request: Request, call_next):
        """Serve `http://<npub>.<host>/<path>` as that pubkey's ROOT site.

        Path-prefixed routes (`/n/<npub>/…`) can't carry root-absolute links
        like `<link href="/style.css">`, because the browser requests them at
        the gateway root with no npub to attribute them to. Giving each site its
        own origin via a subdomain (e.g. `<npub>.localhost:4850`, which browsers
        resolve to 127.0.0.1 with no setup) fixes that: every request under that
        host belongs to one site, so absolute paths just work. Named sites still
        use the `/s/…` path scheme until P2 extends this to `<id>.<npub>.<host>`.
        """
        host = request.headers.get("host", "").split(":")[0]
        label = host.split(".")[0] if "." in host else ""
        if label and (label.startswith("npub1") or len(label) == 64):
            try:
                pubkey = normalize_pubkey(label)
            except ValueError:
                return await call_next(request)
            result = await resolver.resolve(pubkey, request.url.path, "")
            if result is None:
                return Response("not found", status_code=404)
            data, content_type = result
            return Response(content=data, media_type=content_type)
        return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    async def landing():
        return _LANDING

    async def _serve(npub: str, identifier: str, path: str):
        try:
            pubkey = normalize_pubkey(npub)
        except ValueError:
            return Response("invalid npub", status_code=400)
        result = await resolver.resolve(pubkey, "/" + path, identifier)
        if result is None:
            return Response("not found", status_code=404)
        data, content_type = result
        return Response(content=data, media_type=content_type)

    # Root site (with and without a trailing path).
    @app.get("/n/{npub}")
    async def root_index(npub: str):
        return await _serve(npub, "", "")

    @app.get("/n/{npub}/{path:path}")
    async def root_path(npub: str, path: str):
        return await _serve(npub, "", path)

    # Named site.
    @app.get("/s/{npub}/{identifier}")
    async def named_index(npub: str, identifier: str):
        return await _serve(npub, identifier, "")

    @app.get("/s/{npub}/{identifier}/{path:path}")
    async def named_path(npub: str, identifier: str, path: str):
        return await _serve(npub, identifier, path)

    return app
