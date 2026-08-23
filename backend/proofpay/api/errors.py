"""Stable HTTP error envelope shared by every API route."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from proofpay.api.v1.schemas import ApiError

_STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
}

ERROR_RESPONSES = {
    status_code: {"model": ApiError, "description": code.replace("_", " ").title()}
    for status_code, code in _STATUS_CODES.items()
}


def _request_id(request: Request) -> str | None:
    return request.headers.get("X-Request-ID")


def _body(
    request: Request,
    status_code: int,
    message: str,
    *,
    code: str | None = None,
    details: Any = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "code": code or _STATUS_CODES.get(status_code, "INTERNAL_ERROR"),
        "message": message,
    }
    if details is not None:
        body["details"] = details
    request_id = _request_id(request)
    if request_id:
        body["request_id"] = request_id
    return body


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    code = None
    if ":" in detail:
        possible_code, message = detail.split(":", 1)
        if possible_code.isupper() and possible_code.replace("_", "").isalnum():
            code = possible_code
            detail = message.strip()
    return JSONResponse(
        status_code=exc.status_code,
        content=_body(request, exc.status_code, detail, code=code),
        headers=exc.headers,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=_body(request, 422, "Request validation failed", details=exc.errors()),
    )
