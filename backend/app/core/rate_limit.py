"""In-process per-IP rate limiting for the LLM-calling endpoints (P1).

The agent/extract/reflect endpoints are unauthenticated and each one triggers
paid Claude calls, so an unthrottled caller is a Denial-of-Wallet vector
(OWASP LLM10 — Unbounded Consumption; we already hit a credit-drain incident,
see the G22 rework). This is a lightweight, dependency-free sliding-window
limiter — in-process only, matching the project's "no broker" ethos. It is a
cost/abuse guard, **not** a security boundary: it keys on the client IP and a
single process holds the state, so it does not survive a restart or coordinate
across replicas. When real auth lands (G21), key on the authenticated principal.

Crucially it limits how many *runs* a caller may start per window — it never
interrupts a run that is already executing (a single run is bounded by
`max_turns`), so a legitimate multi-step run is never cut off mid-work.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status


class SlidingWindowRateLimiter:
    """Thread-safe sliding-window counter keyed by an arbitrary string.

    `hit` records a request and returns None when it is allowed, or the number
    of seconds to wait (`Retry-After`) when a rule is exceeded. Nothing is
    recorded on a blocked call, so a caller that keeps hammering while blocked
    does not push its own window further out.
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, rules: list[tuple[int, float]]) -> float | None:
        """Record a hit for `key`. `rules` is a list of (limit, window_seconds).

        Returns None if allowed; otherwise the Retry-After seconds (>=1) for the
        first exceeded rule."""
        if not rules:
            return None
        now = time.monotonic()
        max_window = max(window for _, window in rules)
        with self._lock:
            dq = self._hits[key]
            # Drop timestamps older than the widest window so the deque can't grow
            # unbounded for a chatty key.
            cutoff = now - max_window
            while dq and dq[0] <= cutoff:
                dq.popleft()
            for limit, window in rules:
                w_cutoff = now - window
                count = sum(1 for t in dq if t > w_cutoff)
                if count >= limit:
                    oldest_in_window = next((t for t in dq if t > w_cutoff), now)
                    return max(1.0, window - (now - oldest_in_window))
            dq.append(now)
            return None

    def reset(self) -> None:
        """Clear all state (used by tests for per-test isolation)."""
        with self._lock:
            self._hits.clear()


_limiter = SlidingWindowRateLimiter()


def get_limiter() -> SlidingWindowRateLimiter:
    return _limiter


def _client_key(request: Request) -> str:
    client = request.client
    return client.host if client else "unknown"


def llm_rate_limit(request: Request) -> None:
    """FastAPI dependency: throttle the shared per-IP budget for LLM-calling
    endpoints. Settings are read per-request so the limits + enable flag are live.
    """
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.rate_limit_enabled:
        return
    rules = [
        (settings.llm_rate_limit_per_minute, 60.0),
        (settings.llm_rate_limit_per_hour, 3600.0),
    ]
    retry_after = _limiter.hit(_client_key(request), rules)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded — too many requests. Please retry shortly.",
            headers={"Retry-After": str(int(retry_after))},
        )
