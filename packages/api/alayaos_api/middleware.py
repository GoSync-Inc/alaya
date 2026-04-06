"""Error handling middleware and request ID injection."""

import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


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
                    "hint": str(exc.errors()),
                    "docs": None,
                    "request_id": request_id,
                }
            },
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", None)
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
