"""Error handling middleware and request ID injection."""

import json as json_module
import uuid

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.datastructures import URL, Headers
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import RedirectResponse
from structlog.contextvars import bind_contextvars, clear_contextvars


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        clear_contextvars()
        request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        bind_contextvars(request_id=request_id)
        response = await call_next(request)
        request_id = response.headers.get("X-Request-ID", request_id)
        request.state.request_id = request_id
        if response.headers.get("content-type", "").startswith("application/json") and getattr(response, "body", None):
            try:
                payload = json_module.loads(response.body)
            except (TypeError, ValueError):
                payload = None
            if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
                payload["error"]["request_id"] = request_id
                response.body = json_module.dumps(payload).encode("utf-8")
                response.headers["content-length"] = str(len(response.body))
        response.headers["X-Request-ID"] = request_id
        return response


class EnvelopeTrustedHostMiddleware(TrustedHostMiddleware):
    async def __call__(self, scope, receive, send) -> None:
        if self.allow_any or scope["type"] not in ("http", "websocket"):  # pragma: no cover
            await self.app(scope, receive, send)
            return

        clear_contextvars()
        headers = Headers(scope=scope)
        request_id = headers.get("x-request-id", str(uuid.uuid4()))
        scope.setdefault("state", {})["request_id"] = request_id
        bind_contextvars(request_id=request_id)
        host = headers.get("host", "").split(":")[0]
        is_valid_host = False
        found_www_redirect = False
        for pattern in self.allowed_hosts:
            if host == pattern or (pattern.startswith("*") and host.endswith(pattern[1:])):
                is_valid_host = True
                break
            if "www." + host == pattern:
                found_www_redirect = True

        if is_valid_host:
            await self.app(scope, receive, send)
            return

        if found_www_redirect and self.www_redirect:
            url = URL(scope=scope)
            redirect_url = url.replace(netloc="www." + url.netloc)
            response = RedirectResponse(url=str(redirect_url))
            await response(scope, receive, send)
            return

        request_id = scope.get("state", {}).get("request_id")
        response = JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "validation.invalid_host",
                    "message": "Invalid host header.",
                    "hint": None,
                    "docs": None,
                    "request_id": request_id,
                }
            },
        )
        response.headers["X-Request-ID"] = request_id
        await response(scope, receive, send)


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
        headers = exc.headers or None
        # If detail is a dict with "error" key, inject request_id and return directly
        if isinstance(detail, dict) and "error" in detail:
            detail["error"]["request_id"] = request_id
            return JSONResponse(status_code=exc.status_code, content=detail, headers=headers)
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
            headers=headers,
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
