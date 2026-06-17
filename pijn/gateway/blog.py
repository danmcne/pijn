"""
Blog renderer — projects a pubkey's kind-30023 long-form events into a site.

There is no manifest of HTML blobs here: the posts are events, and this module
renders them on the fly (index + per-post pages). The same events are read by
any vanilla NIP-23 client, so the gateway is one rendering among many — exactly
the pijn thesis. The author marks an origin as a blog with one nsite manifest
tagged `app=blog`; the gateway then calls in here.

The byline always shows the npub digest (SPEC §7: a name is never shown without
the unfakeable part of the key beside it).
"""

import html
import time

from .markdown import render as render_markdown
from ..nostr.display import short_npub

_CSS = """
:root{--paper:#fbfbf9;--ink:#1b1a16;--muted:#6c6a62;--line:#e7e4db;--accent:#4b46b4;
--mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;--sans:system-ui,-apple-system,"Segoe UI",sans-serif}
@media(prefers-color-scheme:dark){:root{--paper:#16150f;--ink:#ecebe3;--muted:#9b988c;--line:#2b2920;--accent:#9b95f0}}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);
line-height:1.65;font-size:18px;-webkit-font-smoothing:antialiased}
main{max-width:42rem;margin:0 auto;padding:3rem 1.25rem 4rem}
.eyebrow{font-family:var(--mono);font-size:.74rem;text-transform:uppercase;letter-spacing:.14em;color:var(--accent);margin:0 0 .5rem}
h1{font-size:clamp(1.9rem,5vw,2.7rem);line-height:1.1;font-weight:600;letter-spacing:-.02em;margin:0 0 1rem}
h2{font-size:1.5rem;font-weight:600;margin:2.2rem 0 .8rem;letter-spacing:-.01em}
h3{font-size:1.2rem;font-weight:600;margin:1.8rem 0 .6rem}
p{margin:0 0 1.1rem}a{color:var(--accent)}img{max-width:100%;height:auto;border-radius:6px}
.byline{font-family:var(--mono);font-size:.8rem;color:var(--muted);margin:0 0 2.5rem}
.desc{font-size:1.15rem;color:var(--muted);margin:0 0 2.5rem}
.posts{list-style:none;padding:0;margin:0}
.posts li{padding:1.3rem 0;border-top:1px solid var(--line)}
.posts a{text-decoration:none;color:var(--ink);font-size:1.25rem;font-weight:600;letter-spacing:-.01em}
.posts a:hover{color:var(--accent)}
.meta{font-family:var(--mono);font-size:.74rem;color:var(--muted);margin:.2rem 0 0}
.summary{color:var(--muted);margin:.4rem 0 0}
.back{font-family:var(--mono);font-size:.8rem;color:var(--muted);text-decoration:none;display:inline-block;margin-bottom:2rem}
.back:hover{color:var(--accent)}
article p{font-size:1.06rem}
pre{background:color-mix(in srgb,var(--accent) 9%,transparent);padding:1rem;border-radius:8px;overflow:auto;font-size:.92rem}
code{font-family:var(--mono);font-size:.9em}
pre code{background:none;padding:0}
:not(pre)>code{background:color-mix(in srgb,var(--accent) 12%,transparent);padding:.1em .35em;border-radius:4px}
blockquote{margin:1.2rem 0;padding:.2rem 0 .2rem 1.1rem;border-left:3px solid var(--accent);color:var(--muted)}
hr{border:none;border-top:1px solid var(--line);margin:2rem 0}
:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
"""


def _shell(title: str, body: str) -> bytes:
    page = (f"<!doctype html><html lang=en><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{_CSS}</style>"
            f"<body><main>{body}</main></body></html>")
    return page.encode("utf-8")


def _fmt_date(post) -> str:
    raw = post.first_tag("published_at")
    ts = None
    if raw and raw.isdigit():
        ts = int(raw)
    elif post.created_at:
        ts = int(post.created_at)
    return time.strftime("%Y-%m-%d", time.gmtime(ts)) if ts else ""


def _post_title(post) -> str:
    return post.first_tag("title") or post.d_tag or "untitled"


def render_index(meta: dict, pubkey: str, posts: list) -> bytes:
    """Render the blog landing page: title, byline, and a list of posts."""
    title = meta.get("title") or "Blog"
    items = []
    for p in sorted(posts, key=lambda e: int(e.first_tag("published_at") or e.created_at or 0),
                    reverse=True):
        slug = p.d_tag
        if not slug:
            continue  # an addressable post with no d-tag has no stable URL
        date = _fmt_date(p)
        summary = p.first_tag("summary") or ""
        items.append(
            f"<li><a href='{html.escape(slug, quote=True)}'>{html.escape(_post_title(p))}</a>"
            f"{f'<p class=meta>{date}</p>' if date else ''}"
            f"{f'<p class=summary>{html.escape(summary)}</p>' if summary else ''}</li>"
        )
    body = (f"<p class=eyebrow>Blog</p><h1>{html.escape(title)}</h1>"
            f"<p class=byline>by {short_npub(pubkey)}</p>")
    if meta.get("description"):
        body += f"<p class=desc>{html.escape(meta['description'])}</p>"
    body += (f"<ul class=posts>{''.join(items)}</ul>" if items
             else "<p class=desc>No posts yet.</p>")
    return _shell(title, body)


def render_post(meta: dict, pubkey: str, post) -> bytes:
    """Render a single long-form post."""
    title = _post_title(post)
    date = _fmt_date(post)
    body = (f"<a class=back href='./'>← {html.escape(meta.get('title') or 'Blog')}</a>"
            f"<article><p class=eyebrow>Post</p><h1>{html.escape(title)}</h1>"
            f"<p class=byline>{f'{date} · ' if date else ''}by {short_npub(pubkey)}</p>"
            f"{render_markdown(post.content)}</article>")
    return _shell(title, body)
