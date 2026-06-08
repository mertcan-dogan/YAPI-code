"""Simple in-memory sliding-window rate limiting (Section 8.1).

100 req/min per IP, 1000 req/min per authenticated user. For multi-instance
production this should be backed by Redis; in-memory is adequate for a single
backend instance and keeps v1 dependency-free.

Buckets live at module level so the test suite can reset them between tests
(reset_rate_limits) — each test starts with a clean window.
"""
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.config import settings
from app.responses import error_response

WINDOW = 60.0

_ip_hits: dict[str, deque] = defaultdict(deque)
_user_hits: dict[str, deque] = defaultdict(deque)


def reset_rate_limits() -> None:
    """Clear all rate-limit state (used by the test suite)."""
    _ip_hits.clear()
    _user_hits.clear()


def _allow(bucket: deque, limit: int, now: float) -> bool:
    while bucket and bucket[0] <= now - WINDOW:
        bucket.popleft()
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    return True


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        now = time.monotonic()
        ip = request.client.host if request.client else "unknown"
        if not _allow(_ip_hits[ip], settings.rate_limit_per_ip_per_minute, now):
            return error_response(429, "RATE_LIMITED", "Çok fazla istek. Lütfen biraz bekleyin.")

        # Per-user limit applies once auth has populated request.state (best effort).
        user_id = getattr(request.state, "user_id", None)
        if user_id and not _allow(_user_hits[user_id], settings.rate_limit_per_user_per_minute, now):
            return error_response(429, "RATE_LIMITED", "Çok fazla istek. Lütfen biraz bekleyin.")

        return await call_next(request)
