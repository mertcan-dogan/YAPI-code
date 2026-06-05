"""Standard API response envelope (Appendix C)."""
from typing import Any

from fastapi.responses import JSONResponse


def success(data: Any, meta: dict | None = None) -> dict:
    body: dict[str, Any] = {"success": True, "data": data}
    if meta is not None:
        body["meta"] = meta
    return body


def error_body(code: str, message: str, field: str | None = None) -> dict:
    err: dict[str, Any] = {"code": code, "message": message}
    if field is not None:
        err["field"] = field
    return {"success": False, "error": err}


def error_response(status_code: int, code: str, message: str, field: str | None = None) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error_body(code, message, field))


class APIError(Exception):
    """Raised by services/routers to produce a Section-C error envelope."""

    def __init__(self, status_code: int, code: str, message: str, field: str | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field = field
        super().__init__(message)
