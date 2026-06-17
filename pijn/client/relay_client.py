"""
Nostr relay WebSocket client.

A thin NIP-01 client used by the publisher to push manifest events, and usable
by a standalone gateway to resolve sites from remote relays. Each call opens a
short-lived connection — fine for v1's low volume; a pooled connection can
replace this behind the same methods later.
"""

import json

import websockets

from ..nostr.event import Event


class RelayClient:
    def __init__(self, url: str):
        self.url = url

    async def publish(self, event: Event) -> tuple[bool, str]:
        """Send one EVENT and return the relay's (accepted, message) from OK."""
        async with websockets.connect(self.url) as ws:
            await ws.send(json.dumps(["EVENT", event.to_dict()]))
            while True:
                msg = json.loads(await ws.recv())
                if msg[0] == "OK" and msg[1] == event.id:
                    return bool(msg[2]), (msg[3] if len(msg) > 3 else "")
                if msg[0] == "NOTICE":
                    return False, msg[1]

    async def query(self, filters: list, sub_id: str = "q") -> list:
        """Issue a REQ, collect events until EOSE, then CLOSE. Returns Events."""
        out = []
        async with websockets.connect(self.url) as ws:
            await ws.send(json.dumps(["REQ", sub_id, *filters]))
            while True:
                msg = json.loads(await ws.recv())
                if msg[0] == "EVENT" and msg[1] == sub_id:
                    out.append(Event.from_dict(msg[2]))
                elif msg[0] == "EOSE" and msg[1] == sub_id:
                    await ws.send(json.dumps(["CLOSE", sub_id]))
                    break
        return out
