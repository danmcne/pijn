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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from ..nostr.event import Event
from ..nostr.filters import matches_any


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
    app.state.store = store
    app.state.hub = hub

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
                await _handle_message(ws, raw, store, hub)
        except WebSocketDisconnect:
            pass
        finally:
            hub.remove_socket(ws)

    return app


async def _handle_message(ws, raw, store, hub):
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
        await _handle_event(ws, msg, store, hub)
    elif verb == "REQ":
        await _handle_req(ws, msg, store, hub)
    elif verb == "CLOSE":
        if len(msg) >= 2:
            hub.drop_sub(ws, msg[1])
    else:
        await ws.send_text(json.dumps(["NOTICE", f"unknown verb: {verb}"]))


async def _handle_event(ws, msg, store, hub):
    try:
        event = Event.from_dict(msg[1])
    except (KeyError, IndexError, TypeError):
        await ws.send_text(json.dumps(["OK", "", False, "invalid: malformed event"]))
        return
    if not event.verify():
        await ws.send_text(json.dumps(["OK", event.id, False, "invalid: bad signature"]))
        return
    accepted, reason = store.store(event)
    await ws.send_text(json.dumps(["OK", event.id, accepted, reason]))
    if accepted and reason in ("stored", "ephemeral"):
        await hub.broadcast(event)


async def _handle_req(ws, msg, store, hub):
    if len(msg) < 2:
        await ws.send_text(json.dumps(["NOTICE", "REQ needs a subscription id"]))
        return
    sub_id, filters = msg[1], msg[2:]
    # 1) Replay stored matches (newest first), then 2) keep the sub open for live.
    for event in store.query(filters):
        await ws.send_text(json.dumps(["EVENT", sub_id, event.to_dict()]))
    await ws.send_text(json.dumps(["EOSE", sub_id]))
    hub.set_sub(ws, sub_id, filters)
