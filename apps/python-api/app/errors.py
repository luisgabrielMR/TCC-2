from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: list[dict[str, Any]] | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []


def error_payload(code: str, message: str, details: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or [],
        }
    }


def error_response(status_code: int, code: str, message: str, details: list[dict[str, Any]] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error_payload(code, message, details))


async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message, exc.details)


async def generic_error_handler(_: Request, exc: Exception) -> JSONResponse:
    return error_response(500, "INTERNAL_ERROR", "Internal server error")
