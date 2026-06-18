"""
Tor hidden-service publishing via the control port (P4, inbound).

A small, dependency-free client for the one control-protocol exchange pijn
needs: AUTHENTICATE, then ADD_ONION to map an ephemeral `.onion` onto local
ports. The onion is *attached* to this control connection (no `Detach` flag), so
it exists only while the node runs and disappears cleanly on exit — no stray
hidden services left behind.

Auth supported: null (open control port) and password (`HashedControlPassword`
in torrc → `control_password` in policy). Cookie/SAFECOOKIE auth is not yet
implemented; if your Tor uses it, set a control password instead.

Cautious by design: `app.py` only ever asks this to expose the **gateway**
unless the operator explicitly set `inbound: all`.

This module talks the control protocol over a blocking socket during startup;
the connection is then held open for the process lifetime to keep the onion
alive. No live Tor is bundled — this assumes a Tor daemon with an open
ControlPort, which is the standard setup.
"""

import socket


class TorControlError(RuntimeError):
    pass


class OnionService:
    """An ephemeral Tor hidden service mapping onion virtports to local ports."""

    def __init__(self, host: str, port: int, password: str = ""):
        self.host = host
        self.port = port
        self.password = password
        self._sock: socket.socket | None = None
        self.onion: str | None = None

    # --- control protocol helpers -------------------------------------------
    def _send(self, line: str):
        self._sock.sendall((line + "\r\n").encode("utf-8"))

    def _read_reply(self) -> list[str]:
        """Read one control reply (handles multi-line 250-… / final 250 …)."""
        buf, lines = b"", []
        while True:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise TorControlError("control connection closed")
            buf += chunk
            while b"\r\n" in buf:
                raw, buf = buf.split(b"\r\n", 1)
                line = raw.decode("utf-8", "replace")
                lines.append(line)
                # A final line uses "<code> " (space); continuations use "<code>-".
                if len(line) >= 4 and line[3] == " ":
                    return lines

    def _command(self, line: str) -> list[str]:
        self._send(line)
        reply = self._read_reply()
        if not reply or not reply[-1].startswith("250"):
            raise TorControlError(f"control command failed: {line!r} -> {reply}")
        return reply

    # --- public --------------------------------------------------------------
    def create(self, ports: dict) -> str:
        """Open the control port, authenticate, and publish `ports`.

        `ports` maps onion virtual port -> local "host:port" target, e.g.
        {80: "127.0.0.1:4850"}. Returns the `.onion` hostname.
        """
        self._sock = socket.create_connection((self.host, self.port), timeout=10)
        auth = f'AUTHENTICATE "{self.password}"' if self.password else "AUTHENTICATE"
        self._command(auth)

        portmap = " ".join(f"Port={v},{t}" for v, t in sorted(ports.items()))
        reply = self._command(f"ADD_ONION NEW:BEST Flags=DiscardPK {portmap}")
        service_id = None
        for line in reply:
            # e.g. "250-ServiceID=abcdef...onionidchars"
            if "ServiceID=" in line:
                service_id = line.split("ServiceID=", 1)[1].strip()
        if not service_id:
            raise TorControlError(f"no ServiceID in ADD_ONION reply: {reply}")
        self.onion = service_id + ".onion"
        return self.onion

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None


def reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    """Quick check that a Tor SOCKS/control endpoint is listening."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
