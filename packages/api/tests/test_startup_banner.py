"""Tests for feature flag startup and digest observability."""

from __future__ import annotations

import pytest
import structlog.testing
from fastapi.testclient import TestClient

from alayaos_api.main import create_app
from alayaos_core import config


def test_startup_warns_when_part_of_strict_is_non_default(monkeypatch) -> None:
    monkeypatch.setenv("ALAYA_PART_OF_STRICT", "warn")
    config.get_settings.cache_clear()

    app = create_app()
    with structlog.testing.capture_logs() as logs, TestClient(app):
        pass

    assert {
        "event": "feature_flag_active",
        "flag": "ALAYA_PART_OF_STRICT",
        "value": "warn",
        "default": "strict",
        "log_level": "warning",
    } in logs

    config.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_feature_flag_digest_warns_for_non_default_flags(monkeypatch) -> None:
    monkeypatch.setenv("ALAYA_PART_OF_STRICT", "off")
    config.get_settings.cache_clear()

    from alayaos_core.worker.tasks import job_feature_flag_digest

    with structlog.testing.capture_logs() as logs:
        result = await job_feature_flag_digest.original_func()

    assert result == {"flags_non_default": 1, "status": "checked"}
    assert {
        "event": "feature_flag_active",
        "flag": "ALAYA_PART_OF_STRICT",
        "value": "off",
        "default": "strict",
        "log_level": "warning",
    } in logs

    task_labels = getattr(job_feature_flag_digest, "labels", {})
    assert task_labels["schedule"] == [{"cron": "0 9 * * *"}]

    config.get_settings.cache_clear()
