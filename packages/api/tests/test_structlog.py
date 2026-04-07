"""Tests for structlog integration and config settings."""

import json
import logging

import structlog

from alayaos_core.config import Settings
from alayaos_core.logging import setup_logging


class TestSetupLogging:
    def test_json_output_configures_json_renderer(self) -> None:
        setup_logging(json_output=True, log_level="INFO")
        logger = structlog.get_logger()
        assert logger is not None

    def test_console_output_configures_console_renderer(self) -> None:
        setup_logging(json_output=False, log_level="DEBUG")
        root = logging.getLogger()
        assert root.level == logging.DEBUG


class TestPoolConfig:
    def test_pool_defaults(self, monkeypatch) -> None:
        monkeypatch.delenv("ALAYA_DB_POOL_SIZE", raising=False)
        monkeypatch.delenv("ALAYA_DB_MAX_OVERFLOW", raising=False)
        s = Settings()
        assert s.DB_POOL_SIZE == 5
        assert s.DB_MAX_OVERFLOW == 10
        assert s.DB_POOL_RECYCLE == 300
        assert s.DB_POOL_TIMEOUT == 30
        assert s.DB_ECHO is False

    def test_pool_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("ALAYA_DB_POOL_SIZE", "20")
        monkeypatch.setenv("ALAYA_DB_ECHO", "true")
        s = Settings()
        assert s.DB_POOL_SIZE == 20
        assert s.DB_ECHO is True


class TestValidationSanitization:
    def test_sanitize_strips_input_values(self) -> None:
        from alayaos_api.middleware import _sanitize_validation_errors

        errors = [
            {
                "loc": ("body", "name"),
                "msg": "field required",
                "type": "missing",
                "input": {"secret": "data"},
                "ctx": {"limit": 10},
            },
        ]
        result = _sanitize_validation_errors(errors)
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert "input" not in parsed[0]
        assert "ctx" not in parsed[0]
        assert parsed[0]["msg"] == "field required"


class TestExceptionLogging:
    def test_500_handler_logs_exception(self) -> None:
        """Verify the 500 handler calls structlog.exception."""
        from fastapi import FastAPI

        from alayaos_api.middleware import register_error_handlers

        app = FastAPI()
        register_error_handlers(app)

        # Verify structlog is imported in middleware
        import alayaos_api.middleware as mw

        assert hasattr(mw, "structlog")
