"""Per-client request limits for the endpoints that cost money or disk.

plumb is deployed at a public URL with an LLM key behind it. Without a limit,
anyone who finds the address can spend the owner's provider quota and fill the
host's disk — and that host usually runs other things.

A fixed window per client is enough here. The threat is a script hammering a
public demo, not a distributed attack, and the process is single-instance by
design (sessions hold a live DuckDB connection in memory), so an in-process
counter is as correct as an external store would be.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque

from starlette.requests import Request

WINDOW_SECONDS = 60.0
# Stop the map growing without bound when many clients each make one request.
_MAX_TRACKED_CLIENTS = 10_000


def limit_per_minute() -> int:
    """0 disables the limit — the default for a local run with no key at risk."""
    return int(os.environ.get("PLUMB_RATE_LIMIT_PER_MIN", "0"))


def trusts_forwarded_for() -> bool:
    """Whether X-Forwarded-For may be believed.

    Behind nginx it is the only way to see the real client. Reachable directly,
    it is attacker-controlled: anyone could send a fresh value per request and
    hold their own private allowance. A spoofable limit is worse than none,
    because it reads as protection.
    """
    return os.environ.get("PLUMB_TRUSTED_PROXY", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def client_key(request: Request) -> str:
    if trusts_forwarded_for():
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class Limiter:
    """Fixed-window counter per client, keyed per endpoint group."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, now: float | None = None) -> float | None:
        """None when allowed; otherwise the seconds until the window frees up."""
        allowance = limit_per_minute()
        if allowance <= 0:
            return None
        stamp = time.monotonic() if now is None else now
        with self._lock:
            if len(self._hits) > _MAX_TRACKED_CLIENTS:
                self._hits.clear()
            seen = self._hits[key]
            while seen and stamp - seen[0] > WINDOW_SECONDS:
                seen.popleft()
            if len(seen) >= allowance:
                return WINDOW_SECONDS - (stamp - seen[0])
            seen.append(stamp)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = Limiter()
