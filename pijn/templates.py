"""
Site templates (P2).

`scaffold(dir)` writes a starter site the author edits and then publishes. The
starter is plain HTML/CSS/JS — no build step, consistent with the house stack —
and uses *relative* links throughout, so it renders correctly under a site's
own origin (`<npub>.<host>`) without depending on any path rewriting.

P2 ships the `static` starter here. The blog starter (kind 30023 long-form) is
the next slice and will live alongside it.
"""

import os

_INDEX = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link rel="stylesheet" href="style.css">
<body>
<header class="bar">
  <a class="mark" href="index.html">__TITLE__</a>
  <nav><a href="about.html">About</a></nav>
</header>

<main>
  <p class="eyebrow">A site you own</p>
  <h1>__TITLE__</h1>
  <p class="lede">This page is content-addressed bytes. Its manifest is a signed
  event owned by your key — no host can alter it, and anyone can mirror it.
  Edit these files and run <code>publish</code> again to update the site;
  a new manifest is signed and the old one is superseded.</p>

  <p>Replace this with your own writing. Add pages as plain HTML files next to
  this one and link to them with relative links like
  <a href="about.html">about.html</a>.</p>
</main>

<footer class="bar">
  <span class="origin" id="origin">a pijn identity</span>
</footer>
<script src="app.js"></script>
</body>
</html>
"""

_ABOUT = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>About · __TITLE__</title>
<link rel="stylesheet" href="style.css">
<body>
<header class="bar">
  <a class="mark" href="index.html">__TITLE__</a>
  <nav><a href="index.html">Home</a></nav>
</header>

<main>
  <p class="eyebrow">About</p>
  <h1>About this site</h1>
  <p class="lede">Say who you are. Because identity here is a keypair, you can
  prove this site is yours by signing — and a reader's client can show your
  name beside the part of your key that can't be faked.</p>
</main>

<footer class="bar">
  <span class="origin" id="origin">a pijn identity</span>
</footer>
<script src="app.js"></script>
</body>
</html>
"""

# Restrained identity: paper/ink with one indigo accent, a monospace utility
# face for marks and labels (a nod to keys and hashes), generous rhythm. Dark
# mode mirrors the tokens. No build step, no web fonts.
_STYLE = """:root {
  --paper: #fbfbf9;
  --ink: #1b1a16;
  --muted: #6c6a62;
  --line: #e7e4db;
  --accent: #4b46b4;
  --mono: ui-monospace, "SF Mono", "Cascadia Code", Menlo, Consolas, monospace;
  --sans: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root {
    --paper: #16150f; --ink: #ecebe3; --muted: #9b988c;
    --line: #2b2920; --accent: #9b95f0;
  }
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0; background: var(--paper); color: var(--ink);
  font-family: var(--sans); line-height: 1.65;
  font-size: 18px; -webkit-font-smoothing: antialiased;
}
.bar {
  display: flex; align-items: center; justify-content: space-between;
  gap: 1rem; max-width: 42rem; margin: 0 auto; padding: 1.4rem 1.25rem;
}
.bar + main { padding-top: 0.5rem; }
.mark {
  font-family: var(--mono); font-size: 0.92rem; letter-spacing: -0.01em;
  color: var(--ink); text-decoration: none; font-weight: 500;
}
nav a {
  font-family: var(--mono); font-size: 0.82rem; color: var(--muted);
  text-decoration: none; padding: 0.2rem 0;
  border-bottom: 1px solid transparent;
}
nav a:hover { color: var(--accent); border-bottom-color: var(--accent); }
main { max-width: 42rem; margin: 0 auto; padding: 2.5rem 1.25rem 4rem; }
.eyebrow {
  font-family: var(--mono); font-size: 0.74rem; text-transform: uppercase;
  letter-spacing: 0.14em; color: var(--accent); margin: 0 0 0.6rem;
}
h1 {
  font-size: clamp(2rem, 6vw, 3rem); line-height: 1.08; font-weight: 600;
  letter-spacing: -0.02em; margin: 0 0 1.4rem;
}
.lede { font-size: 1.18rem; color: var(--ink); margin: 0 0 1.4rem; }
p { margin: 0 0 1.1rem; }
a { color: var(--accent); }
code {
  font-family: var(--mono); font-size: 0.88em;
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  padding: 0.1em 0.35em; border-radius: 4px;
}
footer.bar {
  border-top: 1px solid var(--line); margin-top: 3rem;
  justify-content: center; padding-top: 1.4rem;
}
.origin {
  font-family: var(--mono); font-size: 0.76rem; color: var(--muted);
  word-break: break-all; text-align: center;
}
:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
"""

# The signature touch: the footer shows the origin the page is being served
# from — i.e. the identity that owns it. Pure vanilla JS, no dependencies.
_APP = """// Reflect the identity this page is served from. On a pijn gateway the
// hostname is <npub>.<host> (or <identifier>.<npub>.<host>), so the first
// label is the key that owns this site.
(function () {
  var el = document.getElementById("origin");
  if (!el) return;
  var host = location.hostname || "";
  var label = host.split(".")[0] || "";
  if (label.indexOf("npub1") === 0) {
    var short = label.slice(0, 12) + "\\u2026" + label.slice(-4);
    el.textContent = "served from " + short;
  } else {
    el.textContent = "a pijn identity";
  }
})();
"""

_FIRST_POST = """# __TITLE__

Welcome to your pijn blog. This file is a Markdown post. Publish it with:

    python -m pijn post first-post.md --summary "My first post"

That signs a kind-30023 long-form event and sends it to your relay — a standard
NIP-23 article, so any Nostr long-form reader can see it too, not just pijn.

Mark your origin as a blog once, with a title:

    python -m pijn blog --title "__TITLE__"

Then browse it at your `<npub>.localhost:4850/` origin. Edit and re-`post` the
same file to update it (the slug stays the same; the relay supersedes the old
version). Write in **bold**, *italic*, `code`, lists, and [links](https://example.com).
"""

_STATIC_FILES = {
    "index.html": _INDEX,
    "about.html": _ABOUT,
    "style.css": _STYLE,
    "app.js": _APP,
}

_BLOG_FILES = {
    "first-post.md": _FIRST_POST,
}


def scaffold(directory: str, kind: str = "static", title: str = "My pijn site") -> list:
    """Write a starter site into `directory`. Returns the relative paths created."""
    files = {"static": _STATIC_FILES, "blog": _BLOG_FILES}.get(kind)
    if files is None:
        raise ValueError(f"unknown template: {kind!r}")
    os.makedirs(directory, exist_ok=True)
    created = []
    for name, body in files.items():
        path = os.path.join(directory, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body.replace("__TITLE__", title))
        created.append(name)
    return sorted(created)
