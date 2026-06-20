"""CR-011 streaming fix — the custom middleware stack must pass a
StreamingResponse through UNBUFFERED so SSE (POST /ai/agent?stream=1) streams
chunk-by-chunk in prod, not all-at-once.

The bug: SecurityHeaders/RateLimit/CatchAll were ``BaseHTTPMiddleware``, which
routes the response body through anyio memory streams; stacked, they buffer/
serialize the stream. The fix converts them to **pure ASGI** middleware (which
forward each ``send`` event untouched) AND makes the endpoint's SSE generator an
async generator (so Starlette never parks a threadpool worker on it).

This module asserts the regression-critical property *structurally* — the three
custom middlewares are no longer ``BaseHTTPMiddleware``. (We deliberately do NOT
drive the ASGI app through a raw event loop in-process to assert byte-streaming:
doing so corrupts the anyio portal that Starlette's TestClient uses in later
tests and deadlocks the suite. The real "it actually streams" proof is a
``curl -N`` against a running server; the endpoint's streaming path is also
exercised end-to-end by tests/test_cr011a_streaming.py via the TestClient.)
"""
from starlette.middleware.base import BaseHTTPMiddleware

from app.middleware.errors import CatchAllErrorMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware


def test_custom_middlewares_are_pure_asgi():
    """Pure-ASGI middleware forwards every send event untouched → a
    StreamingResponse streams. Re-introducing BaseHTTPMiddleware would buffer it,
    so guard against exactly that."""
    for cls in (CatchAllErrorMiddleware, SecurityHeadersMiddleware, RateLimitMiddleware):
        assert not issubclass(cls, BaseHTTPMiddleware), f"{cls.__name__} would buffer streaming"
        # Pure-ASGI shape: constructed with the inner app, callable as (scope, receive, send).
        assert hasattr(cls, "__call__")
        assert "dispatch" not in vars(cls), f"{cls.__name__} still uses BaseHTTPMiddleware.dispatch"
