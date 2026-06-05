"""Exception handlers producing the Section-C error envelope, in Turkish."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.responses import APIError, error_response

logger = logging.getLogger("yapi.errors")


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
