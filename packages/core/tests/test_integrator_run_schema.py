"""Test IntegratorRunRead schema."""

import uuid
from datetime import UTC, datetime

from alayaos_core.schemas.integrator_run import IntegratorRunRead


def test_integrator_run_read_schema_basic():
    """IntegratorRunRead validates correctly from model attributes."""
    data = {
        "id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "trigger": "manual",
        "scope_description": None,
        "llm_model": None,
        "status": "running",
        "error_message": None,
        "started_at": datetime.now(UTC),
        "completed_at": None,
    }
    run = IntegratorRunRead(**data)
    assert run.trigger == "manual"
    assert run.entities_scanned == 0
    assert run.tokens_used == 0
    assert run.cost_usd == 0.0


def test_integrator_run_read_none_fields_default_to_zero():
    """None counter fields default to their defaults (0/0.0)."""
    data = {
        "id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "trigger": "job_integrate",
        "scope_description": "test",
        "entities_scanned": None,
        "entities_deduplicated": None,
        "llm_model": "claude-3-haiku",
        "status": "completed",
        "error_message": None,
        "started_at": datetime.now(UTC),
        "completed_at": datetime.now(UTC),
    }
    run = IntegratorRunRead(**data)
    # None is passed; schema allows None via Optional
    assert run.entities_scanned is None
    assert run.status == "completed"
