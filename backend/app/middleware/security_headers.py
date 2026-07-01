"""HTTP security headers (CR-002-I 10.6).

CR-011 streaming fix: implemented as a **pure ASGI** middleware (not
BaseHTTPMiddleware) so it never buffers the response body — it only augments the
``http.response.start`` headers and forwards every event untouched, letting a
StreamingResponse (SSE) stream chunk-by-chunk.
"""
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'self'",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for key, value in SECURITY_HEADERS.items():
                    # setdefault semantics — never override a header the route set.
                    if key not in headers:
                        headers[key] = value
            await send(message)

        await self.app(scope, receive, send_wrapper)
