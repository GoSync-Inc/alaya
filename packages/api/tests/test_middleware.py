"""Tests for middleware: RequestIDMiddleware and error handlers."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from alayaos_api.middleware import register_error_handlers


def make_test_app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/ok")
    async def ok():
        return {"status": "ok"}

    @app.get("/error")
    async def error():
        raise RuntimeError("boom")

    @app.get("/bad")
    async def bad(x: int):  # int query param — will fail validation if not int
        return {"x": x}

    return app


def test_request_id_header_echoed() -> None:
    app = make_test_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/ok", headers={"X-Request-ID": "test-123"})
    assert response.headers["X-Request-ID"] == "test-123"


def test_request_id_generated_if_missing() -> None:
    app = make_test_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/ok")
    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) > 0


def test_generic_exception_returns_500_envelope() -> None:
    app = make_test_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/error")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "server.internal_error"


def test_validation_error_returns_400_envelope() -> None:
    app = make_test_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/bad?x=notanint")
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "validation.invalid_input"
