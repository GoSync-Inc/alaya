"""Error handling middleware and request ID injection."""

import json as json_module
import uuid

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from structlog.contextvars import bind_contextvars, clear_contextvars


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        clear_contextvars()
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        bind_contextvars(request_id=request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


def _sanitize_validation_errors(errors: list[dict]) -> str:
    """Strip input/ctx from validation errors to prevent data leakage."""
    sanitized = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in errors]
    return json_module.dumps(sanitized)


def register_error_handlers(app: FastAPI) -> None:
    app.add_middleware(RequestIDMiddleware)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        request_id = getattr(request.state, "request_id", None)
        detail = exc.detail
        # If detail is a dict with "error" key, inject request_id and return directly
        if isinstance(detail, dict) and "error" in detail:
            detail["error"]["request_id"] = request_id
            return JSONResponse(status_code=exc.status_code, content=detail)
        # Fallback for plain string detail
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": "server.internal_error",
                    "message": str(detail),
                    "hint": None,
                    "docs": None,
                    "request_id": request_id,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        request_id = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "validation.invalid_input",
                    "message": "Request validation failed.",
                    "hint": _sanitize_validation_errors(exc.errors()),
                    "docs": None,
                    "request_id": request_id,
                }
            },
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", None)
        logger = structlog.get_logger()
        logger.exception("unhandled_exception", path=request.url.path, request_id=request_id)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "server.internal_error",
                    "message": "An unexpected error occurred.",
                    "hint": None,
                    "docs": None,
                    "request_id": request_id,
                }
            },
        )
