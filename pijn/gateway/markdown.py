"""
Minimal Markdown → HTML, for rendering kind-30023 long-form posts.

This is a deliberately small CommonMark *subset* — headings, paragraphs, fenced
and inline code, bold/italic, links, images, blockquotes, flat lists, and rules.
It is not a full CommonMark implementation; a complete one can drop in behind
`render()` later (the same "build a small thing for v1, keep the option open"
stance used for the crypto).

Safety is the priority, because the gateway renders Markdown authored by
*arbitrary* pubkeys: all text is HTML-escaped, raw HTML is never passed through,
and URLs are sanitized so `javascript:`/`data:` schemes can't produce script.
The per-site origin (each npub on its own subdomain) further contains anything
that slips through to that author's own origin.
"""

import html
import re

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_HR = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})\s*$")
_UL = re.compile(r"^\s*[-*+]\s+(.*)$")
_OL = re.compile(r"^\s*\d+\.\s+(.*)$")
_QUOTE = re.compile(r"^>\s?(.*)$")
_FENCE = re.compile(r"^```")


# All control chars and spaces. Browsers strip these *before* parsing a URL
# scheme, so "java\tscript:" would execute despite a naive "startswith" check —
# we remove them entirely so the scheme test sees the real scheme.
_URL_CTRL = re.compile(r"[\x00-\x20\x7f-\x9f]")
# Scheme allowlist (not a denylist): only these absolute schemes are emitted;
# anything else with a scheme is dropped. Relative/anchor/protocol-relative URLs
# have no scheme and so cannot be javascript:/data:/vbscript:.
_ALLOWED_SCHEMES = ("http://", "https://", "mailto:")


def _safe_url(url: str) -> str:
    """Make a URL safe for an HTML attribute: allow only known-safe schemes.

    Uses an allowlist rather than blocking specific dangerous schemes, and
    strips embedded control characters first so scheme-spoofing tricks like
    `java\\tscript:` cannot slip through.
    """
    cleaned = _URL_CTRL.sub("", url)
    low = cleaned.lower()
    # Is there a scheme (a ':' before the first '/')? If so, require an allowed
    # one; if not, it's a relative/anchor URL and is safe.
    if ":" in low.split("/", 1)[0] and not low.startswith(_ALLOWED_SCHEMES):
        return "#"
    # The surrounding inline text was already html.escape(quote=False)'d, so
    # &/</> are handled; finish attribute-safety by escaping quotes only, to
    # avoid double-escaping '&' (which would corrupt query strings).
    return cleaned.replace('"', "&quot;").replace("'", "&#x27;")


def _inline(text: str) -> str:
    """Render inline spans. Code spans are protected from other transforms."""
    codes = []

    def stash(m):
        codes.append(html.escape(m.group(1), quote=False))
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", stash, text)
    text = html.escape(text, quote=False)

    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)",
                  lambda m: f'<img src="{_safe_url(m.group(2))}" alt="{html.escape(m.group(1), quote=True)}">',
                  text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
                  lambda m: f'<a href="{_safe_url(m.group(2))}">{m.group(1)}</a>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*(?!\s)([^*]+?)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"(?<!_)_(?!\s)([^_]+?)_(?!_)", r"<em>\1</em>", text)

    return re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{codes[int(m.group(1))]}</code>", text)


def render(md: str) -> str:
    """Render a Markdown string to a safe HTML fragment."""
    lines = md.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out, i, n = [], 0, len(lines)

    while i < n:
        line = lines[i]

        if _FENCE.match(line):
            i += 1
            buf = []
            while i < n and not _FENCE.match(lines[i]):
                buf.append(lines[i])
                i += 1
            i += 1  # closing fence
            out.append(f"<pre><code>{html.escape(chr(10).join(buf), quote=False)}</code></pre>")
            continue

        if not line.strip():
            i += 1
            continue

        m = _HEADING.match(line)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2).strip())}</h{level}>")
            i += 1
            continue

        if _HR.match(line):
            out.append("<hr>")
            i += 1
            continue

        if _QUOTE.match(line):
            buf = []
            while i < n and _QUOTE.match(lines[i]):
                buf.append(_QUOTE.match(lines[i]).group(1))
                i += 1
            out.append(f"<blockquote>{_inline(' '.join(buf))}</blockquote>")
            continue

        if _UL.match(line) or _OL.match(line):
            ordered = bool(_OL.match(line))
            pat = _OL if ordered else _UL
            items = []
            while i < n and pat.match(lines[i]):
                items.append(f"<li>{_inline(pat.match(lines[i]).group(1).strip())}</li>")
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>{''.join(items)}</{tag}>")
            continue

        # Paragraph: gather until a blank line or a block starter.
        buf = []
        while i < n and lines[i].strip() and not (
            _HEADING.match(lines[i]) or _HR.match(lines[i]) or _FENCE.match(lines[i])
            or _UL.match(lines[i]) or _OL.match(lines[i]) or _QUOTE.match(lines[i])
        ):
            buf.append(lines[i])
            i += 1
        out.append(f"<p>{_inline(' '.join(buf))}</p>")

    return "\n".join(out)
