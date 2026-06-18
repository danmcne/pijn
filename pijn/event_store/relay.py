"""
Minimal Nostr relay (NIP-01) over WebSocket.

Client -> relay messages handled:  EVENT, REQ, CLOSE
Relay  -> client messages emitted:  OK, EVENT, EOSE, CLOSED, NOTICE

This is the "build for v1" relay: small, in our control, stack-fitting. Its
inputs/outputs are exactly NIP-01, so a hardened relay (strfry/khatru) can be
dropped in for public nodes later without changing any caller. Storage rules
live in event_store.db; this module is just the protocol surface plus a tiny
subscription hub for live fan-out.
"""

import json
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from ..moderation import Moderation
from ..nostr.event import Event
from ..nostr.filters import matches_any

# Ingest/serve guardrails — relevant the moment the relay is reachable (P4).
# The built-in relay is for personal nodes; a public node still swaps in
# strfry/khatru, but these keep an exposed personal node from trivial abuse.
MAX_SUBSCRIPTIONS = 32        # open subscriptions per connection
MAX_FILTERS = 16             # filters per REQ
DEFAULT_QUERY_LIMIT = 500     # cap a filter that names no `limit`
MAX_QUERY_LIMIT = 5000        # cap on any `limit` a client asks for
MAX_FUTURE_SECS = 900         # reject events dated > 15 min ahead (clock skew slack)


class Hub:
    """Tracks open subscriptions so newly stored events can be pushed live.

    Maps each connected WebSocket to {sub_id: filters}. Kept in memory; a
    restart simply drops live subscriptions (clients re-REQ).
    """

    def __init__(self):
        self._subs: dict[WebSocket, dict[str, list]] = {}

    def add_socket(self, ws):
        self._subs[ws] = {}

    def remove_socket(self, ws):
        self._subs.pop(ws, None)

    def set_sub(self, ws, sub_id, filters):
        self._subs.setdefault(ws, {})[sub_id] = filters

    def sub_count(self, ws) -> int:
        return len(self._subs.get(ws, {}))

    def has_sub(self, ws, sub_id) -> bool:
        return sub_id in self._subs.get(ws, {})

    def drop_sub(self, ws, sub_id):
        self._subs.get(ws, {}).pop(sub_id, None)

    async def broadcast(self, event: Event):
        """Send a freshly accepted event to every matching open subscription."""
        for ws, subs in list(self._subs.items()):
            for sub_id, filters in list(subs.items()):
                if matches_any(event, filters):
                    try:
                        await ws.send_text(json.dumps(["EVENT", sub_id, event.to_dict()]))
                    except Exception:
                        # Drop dead sockets silently; disconnect handler cleans up.
                        pass


def build_relay_app(store, policy=None) -> FastAPI:
    """Construct the relay FastAPI app bound to a given EventStore."""
    app = FastAPI(title="pijn relay")
    hub = Hub()
    moderation = Moderation.from_policy(policy) if policy is not None else Moderation(None)
    app.state.store = store
    app.state.hub = hub
    app.state.moderation = moderation

    @app.get("/")
    async def info():
        # A human/diagnostic landing payload. (NIP-11 relay info could go here.)
        return {"service": "pijn-relay", "events": store.count()}

    @app.websocket("/")
    async def relay_socket(ws: WebSocket):
        await ws.accept()
        hub.add_socket(ws)
        try:
            while True:
                raw = await ws.receive_text()
                await _handle_message(ws, raw, store, hub, moderation)
        except WebSocketDisconnect:
            pass
        finally:
            hub.remove_socket(ws)

    return app


async def _handle_message(ws, raw, store, hub, moderation):
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        await ws.send_text(json.dumps(["NOTICE", "invalid JSON"]))
        return
    if not isinstance(msg, list) or not msg:
        await ws.send_text(json.dumps(["NOTICE", "expected a non-empty array"]))
        return

    verb = msg[0]
    if verb == "EVENT":
        await _handle_event(ws, msg, store, hub, moderation)
    elif verb == "REQ":
        await _handle_req(ws, msg, store, hub)
    elif verb == "CLOSE":
        if len(msg) >= 2:
            hub.drop_sub(ws, msg[1])
    else:
        await ws.send_text(json.dumps(["NOTICE", f"unknown verb: {verb}"]))


async def _handle_event(ws, msg, store, hub, moderation):
    try:
        event = Event.from_dict(msg[1])
    except (KeyError, IndexError, TypeError):
        await ws.send_text(json.dumps(["OK", "", False, "invalid: malformed event"]))
        return
    if not event.verify():
        await ws.send_text(json.dumps(["OK", event.id, False, "invalid: bad signature"]))
        return
    if event.created_at > int(time.time()) + MAX_FUTURE_SECS:
        await ws.send_text(json.dumps(["OK", event.id, False, "invalid: created_at too far in the future"]))
        return
    if not moderation.accepts_event(event):
        await ws.send_text(json.dumps(["OK", event.id, False, "blocked: not accepted by relay policy"]))
        return
    accepted, reason = store.store(event)
    await ws.send_text(json.dumps(["OK", event.id, accepted, reason]))
    if accepted and reason in ("stored", "ephemeral"):
        await hub.broadcast(event)


def _cap_filters(filters: list) -> list:
    """Bound filter count and force a sane per-filter `limit`, so a broad REQ
    can't stream the whole store."""
    capped = []
    for flt in filters[:MAX_FILTERS]:
        if not isinstance(flt, dict):
            continue
        lim = flt.get("limit")
        try:
            lim = int(lim) if lim is not None else DEFAULT_QUERY_LIMIT
        except (TypeError, ValueError):
            lim = DEFAULT_QUERY_LIMIT
        flt = {**flt, "limit": max(0, min(lim, MAX_QUERY_LIMIT))}
        capped.append(flt)
    return capped


async def _handle_req(ws, msg, store, hub):
    if len(msg) < 2:
        await ws.send_text(json.dumps(["NOTICE", "REQ needs a subscription id"]))
        return
    sub_id, filters = msg[1], _cap_filters(msg[2:])
    if hub.sub_count(ws) >= MAX_SUBSCRIPTIONS and not hub.has_sub(ws, sub_id):
        await ws.send_text(json.dumps(["CLOSED", sub_id, "rate-limited: too many subscriptions"]))
        return
    # 1) Replay stored matches (newest first), then 2) keep the sub open for live.
    for event in store.query(filters):
        await ws.send_text(json.dumps(["EVENT", sub_id, event.to_dict()]))
    await ws.send_text(json.dumps(["EOSE", sub_id]))
    hub.set_sub(ws, sub_id, filters)
