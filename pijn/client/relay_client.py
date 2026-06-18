"""
Nostr relay WebSocket client.

A thin NIP-01 client used by the publisher to push manifest events, and usable
by a standalone gateway to resolve sites from remote relays. Each call opens a
short-lived connection — fine for v1's low volume; a pooled connection can
replace this behind the same methods later.
"""

import json

import asyncio

import websockets

from ..nostr.event import Event


class RelayClient:
    def __init__(self, url: str, proxy: str | None = None):
        self.url = url
        self.proxy = proxy  # e.g. "socks5h://127.0.0.1:9050" to route over Tor

    async def publish(self, event: Event, timeout: float = 10) -> tuple[bool, str]:
        """Send one EVENT and return the relay's (accepted, message) from OK."""
        async with websockets.connect(self.url, proxy=self.proxy) as ws:
            await ws.send(json.dumps(["EVENT", event.to_dict()]))
            while True:
                try:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout))
                except asyncio.TimeoutError:
                    return False, "timeout waiting for OK"
                if msg[0] == "OK" and msg[1] == event.id:
                    return bool(msg[2]), (msg[3] if len(msg) > 3 else "")
                if msg[0] == "NOTICE":
                    return False, msg[1] if len(msg) > 1 else "notice"

    async def query(self, filters: list, sub_id: str = "q", timeout: float = 10) -> list:
        """Issue a REQ, collect events until EOSE, then CLOSE. Returns Events.

        Terminates on EOSE, on a CLOSED for our subscription (e.g. the relay
        rejected a filter), or on `timeout` seconds of silence — so a relay that
        never sends EOSE can't hang the caller forever.
        """
        out = []
        async with websockets.connect(self.url, proxy=self.proxy) as ws:
            await ws.send(json.dumps(["REQ", sub_id, *filters]))
            while True:
                try:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout))
                except asyncio.TimeoutError:
                    break
                if msg[0] == "EVENT" and msg[1] == sub_id:
                    try:
                        out.append(Event.from_dict(msg[2]))
                    except (KeyError, IndexError, TypeError):
                        continue  # skip a malformed event rather than abort the query
                elif msg[0] == "EOSE" and msg[1] == sub_id:
                    await ws.send(json.dumps(["CLOSE", sub_id]))
                    break
                elif msg[0] == "CLOSED" and msg[1] == sub_id:
                    break
        return out
