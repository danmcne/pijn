"""
Blossom server (BUD-01 / BUD-02) over HTTP.

Endpoints:
    PUT    /upload          store a blob (auth: t=upload, x=sha256 of body)
    GET    /<sha256>[.ext]   fetch a blob (public)
    HEAD   /<sha256>[.ext]   existence + size (public)
    DELETE /<sha256>         delete a blob you own (auth: t=delete, x=sha256)
    GET    /list/<pubkey>    list a pubkey's blob descriptors (public)

Reads are public; writes are authorized by a signed kind-24242 token (see
auth.py). The server owns bytes only — never events.
"""

import mimetypes
import re

from fastapi import FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse

from .auth import verify_auth
from .storage import BlobStore, sha256_hex

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _strip_ext(sha_with_ext: str) -> str:
    """`<sha>.png` -> `<sha>`; leave a bare hash untouched."""
    return sha_with_ext.split(".", 1)[0].lower()


def _valid_sha(sha: str) -> bool:
    """A blob name must be exactly a 64-char lowercase hex sha256. Validating at
    the boundary is defence-in-depth against any path-traversal attempt (the DB
    metadata gate already blocks unknown names, but we don't want to rely on it
    alone)."""
    return bool(_SHA256_RE.match(sha))


def _guess_type(stored_type: str, sha_with_ext: str) -> str:
    if stored_type:
        return stored_type
    guessed, _ = mimetypes.guess_type(sha_with_ext)
    return guessed or "application/octet-stream"


def build_blob_app(store: BlobStore, public_url: str = "", max_size: int = 0,
                   moderation=None) -> FastAPI:
    app = FastAPI(title="pijn blossom")
    app.state.store = store

    @app.put("/upload")
    async def upload(request: Request, authorization: str = Header(default="")):
        # Reject oversized uploads before buffering the whole body, when the
        # client declares a length; the post-read check below is the backstop.
        if max_size:
            declared = request.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > max_size:
                return JSONResponse(
                    {"message": f"blob exceeds max size {max_size}"}, status_code=413
                )
        data = await request.body()
        if max_size and len(data) > max_size:
            return JSONResponse(
                {"message": f"blob exceeds max size {max_size}"}, status_code=413
            )
        sha = sha256_hex(data)
        pubkey = verify_auth(authorization, "upload", sha)
        if pubkey is None:
            return JSONResponse({"message": "unauthorized"}, status_code=401)
        # Moderation: a "knowing operator" refuses content their policy excludes,
        # by uploader pubkey or by exact blob hash (SPEC §4).
        if moderation is not None and not moderation.accepts_blob(sha, pubkey):
            return JSONResponse({"message": "blocked by operator policy"}, status_code=403)
        descriptor = store.put(
            data, content_type=request.headers.get("content-type", ""), pubkey=pubkey
        )
        descriptor["url"] = f"{public_url}/{sha}" if public_url else f"/{sha}"
        return descriptor

    @app.api_route("/list/{pubkey}", methods=["GET"])
    async def list_blobs(pubkey: str):
        return store.list_by_pubkey(pubkey, base_url=public_url)

    @app.api_route("/{sha_with_ext}", methods=["GET", "HEAD"])
    async def fetch(sha_with_ext: str, request: Request):
        sha = _strip_ext(sha_with_ext)
        if not _valid_sha(sha):
            return Response(status_code=404)
        meta = store.meta(sha)
        if meta is None or not store.has(sha):
            return Response(status_code=404)
        media_type = _guess_type(meta["type"], sha_with_ext)
        if request.method == "HEAD":
            return Response(
                status_code=200,
                headers={"content-length": str(meta["size"]), "content-type": media_type},
            )
        return Response(content=store.get(sha), media_type=media_type)

    @app.delete("/{sha}")
    async def delete(sha: str, authorization: str = Header(default="")):
        sha = _strip_ext(sha)
        if not _valid_sha(sha):
            return JSONResponse({"message": "invalid sha"}, status_code=400)
        pubkey = verify_auth(authorization, "delete", sha)
        if pubkey is None:
            return JSONResponse({"message": "unauthorized"}, status_code=401)
        ok, message = store.delete(sha, pubkey)
        return JSONResponse({"message": message}, status_code=200 if ok else 403)

    return app
