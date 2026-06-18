"""
Moderation — the "knowing operator" accept/refuse decision (SPEC §4).

This is what `mode` + `pubkeys.allow/block` + `content.allow/block` actually
*do*: every event a relay is asked to store, and every blob a Blossom upload
would create, is checked here first. Precedence, most specific wins:

  1. content.block   — never carry this exact item (event id or blob sha256).
  2. content.allow   — carry this item even if its author isn't allowed / is
                       blocked (a warning is logged when it overrides a blocked
                       author and `warn_on_override` is set).
  3. pubkeys.block   — refuse this author's other content.
  4. pubkeys.allow   — carry this author (the inclusion rule in opt-in mode).
  5. mode default    — opt-in: carry nothing else; opt-out: carry all not blocked.

Default when a policy has **no** `moderation:` section: `opt-out` with empty
lists, i.e. carry everything — so adding moderation is opt-in and a node without
it behaves exactly as before. `npub` entries are normalized to hex.
"""

import sys


def _norm_pubkeys(values):
    from .nostr.bech32 import normalize_pubkey
    out = set()
    for v in values or []:
        try:
            out.add(normalize_pubkey(v))
        except Exception:
            out.add(v)  # leave hex/unknown as-is
    return out


class Moderation:
    def __init__(self, raw_moderation: dict | None):
        m = raw_moderation or {}
        self.configured = bool(raw_moderation)
        self.mode = (m.get("mode") or "opt-out").lower()
        pk = m.get("pubkeys") or {}
        self.pub_allow = _norm_pubkeys(pk.get("allow"))
        self.pub_block = _norm_pubkeys(pk.get("block"))
        content = m.get("content") or {}
        self.content_allow = set(content.get("allow") or [])
        self.content_block = set(content.get("block") or [])
        self.warn_on_override = bool(m.get("warn_on_override", True))

    @classmethod
    def from_policy(cls, policy) -> "Moderation":
        return cls((getattr(policy, "raw", {}) or {}).get("moderation"))

    def _decide(self, item_id: str, author: str) -> bool:
        if item_id in self.content_block:                 # 1
            return False
        if item_id in self.content_allow:                 # 2
            if self.warn_on_override and author in self.pub_block:
                print(f"pijn: moderation — carrying {item_id[:12]}… via content.allow "
                      f"despite blocked author {author[:12]}…", file=sys.stderr)
            return True
        if author in self.pub_block:                      # 3
            return False
        if author in self.pub_allow:                      # 4
            return True
        return self.mode != "opt-in"                      # 5

    def accepts_event(self, event) -> bool:
        """True iff this event may be stored under the operator's policy."""
        return self._decide(event.id, event.pubkey)

    def accepts_blob(self, sha: str, uploader_pubkey: str) -> bool:
        """True iff a blob with this sha (uploaded by this pubkey) may be kept."""
        return self._decide(sha, uploader_pubkey)
