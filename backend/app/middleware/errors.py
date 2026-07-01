"""Exception handlers producing the Section-C error envelope, in Turkish."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.responses import APIError, error_response

logger = logging.getLogger("yapi.errors")


class CatchAllErrorMiddleware:
    """Convert any unhandled exception into the standard 500 error envelope.

    FastAPI's catch-all ``Exception`` handler runs in Starlette's
    ServerErrorMiddleware, which sits *outside* every user middleware —
    including CORSMiddleware. A 500 produced there therefore carries no
    ``Access-Control-Allow-Origin`` header, so the browser reports a genuine
    backend error as a misleading CORS failure.

    Registering this middleware *inside* CORSMiddleware means the error response
    is generated here and travels back out through the CORS layer, picking up
    the proper CORS headers. Handled errors (APIError, HTTPException, validation)
    are dealt with by ExceptionMiddleware below this point and never reach here.

    CR-011 streaming fix: this is a **pure ASGI** middleware (not
    BaseHTTPMiddleware) so it forwards each ``send`` event untouched — a
    StreamingResponse (SSE on POST /ai/agent?stream=1) streams chunk-by-chunk
    instead of being buffered. We only intervene when an exception escapes
    BEFORE the response has started; once bytes are on the wire we cannot inject
    a new response, so we re-raise.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:  # noqa: BLE001 — last-resort backstop
            logger.exception("Unhandled error: %s", exc)
            if response_started:
                # Bytes already flushed (e.g. mid-stream) — cannot replace the
                # response; let it propagate so the server closes the connection.
                raise
            await error_response(500, "INTERNAL_ERROR", "Beklenmeyen bir hata oluştu")(
                scope, receive, send
            )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def _api_error(request: Request, exc: APIError):
        return error_response(exc.status_code, exc.code, exc.message, exc.field)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        # Surface the first error with its field and Turkish message (Section 9.3).
        first = exc.errors()[0] if exc.errors() else {}
        loc = first.get("loc", [])
        field = loc[-1] if loc else None
        message = first.get("msg", "Doğrulama hatası")
        # Pydantic prefixes custom ValueError messages with "Value error, ".
        message = message.replace("Value error, ", "")
        return error_response(422, "VALIDATION_ERROR", message, str(field) if field else None)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        code = {401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND"}.get(
            exc.status_code, "HTTP_ERROR"
        )
        message = exc.detail if isinstance(exc.detail, str) else "İstek işlenemedi"
        return error_response(exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        logger.exception("Unhandled error: %s", exc)
        return error_response(500, "INTERNAL_ERROR", "Beklenmeyen bir hata oluştu")
