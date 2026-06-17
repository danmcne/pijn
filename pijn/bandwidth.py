"""
Bandwidth budget (P3).

A small persisted meter for replication *download* traffic, enforced against a
daily and a monthly ceiling (`limits.bandwidth_day` / `bandwidth_month`). The
counters live in a JSON file so the budget survives restarts; they roll over
automatically when the UTC day or month changes.

The controller asks `allow(n)` before fetching a blob and `record(n)` after, so
a node won't blow past the data cap its operator set — even for pinned sites,
since bandwidth is a hard external limit (unlike storage caps, which `pin`
bypasses). Serving/upload accounting is a later refinement; this meters pulls.
"""

import json
import os
import time


class BandwidthMeter:
    def __init__(self, path: str, day_cap: int = 0, month_cap: int = 0):
        self.path = path
        self.day_cap = day_cap          # bytes; 0 = unlimited
        self.month_cap = month_cap
        self.state = {"date": "", "month": "", "day": 0, "month_bytes": 0}
        try:
            with open(self.path) as f:
                self.state.update(json.load(f))
        except Exception:
            pass
        self._roll()

    def _roll(self):
        today = time.strftime("%Y-%m-%d", time.gmtime())
        month = today[:7]
        if self.state.get("date") != today:
            self.state["date"], self.state["day"] = today, 0
        if self.state.get("month") != month:
            self.state["month"], self.state["month_bytes"] = month, 0

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "w") as f:
                json.dump(self.state, f)
        except Exception:
            pass

    def allow(self, nbytes: int) -> bool:
        self._roll()
        if self.day_cap and self.state["day"] + nbytes > self.day_cap:
            return False
        if self.month_cap and self.state["month_bytes"] + nbytes > self.month_cap:
            return False
        return True

    def record(self, nbytes: int):
        self._roll()
        self.state["day"] += nbytes
        self.state["month_bytes"] += nbytes
        self._save()

    def remaining(self) -> tuple:
        """(day_remaining, month_remaining) in bytes; None where uncapped."""
        self._roll()
        d = (self.day_cap - self.state["day"]) if self.day_cap else None
        m = (self.month_cap - self.state["month_bytes"]) if self.month_cap else None
        return d, m
