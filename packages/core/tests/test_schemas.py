"""Tests for Pydantic schemas (Task 5)."""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from alayaos_core.schemas.api_key import APIKeyCreate, APIKeyCreateResponse, APIKeyRead
from alayaos_core.schemas.common import (
    ErrorDetail,
    ErrorResponse,
    HealthCheck,
    HealthResponse,
    PaginatedResponse,
    PaginationInfo,
)
from alayaos_core.schemas.entity import EntityCreate, EntityRead, EntityUpdate
from alayaos_core.schemas.entity_type import EntityTypeCreate, EntityTypeRead
from alayaos_core.schemas.event import EventCreate, EventRead
from alayaos_core.schemas.predicate import PredicateCreate, PredicateRead
from alayaos_core.schemas.workspace import WorkspaceCreate, WorkspaceRead, WorkspaceUpdate

# ─── Common schemas ───────────────────────────────────────────────────────────


def test_error_detail_fields() -> None:
    err = ErrorDetail(field="name", message="required")
    assert err.field == "name"
    assert err.message == "required"


def test_error_response_fields() -> None:
    resp = ErrorResponse(error="bad_request", message="Something went wrong")
    assert resp.error == "bad_request"


def test_pagination_info_fields() -> None:
    p = PaginationInfo(total=100, page=1, page_size=20, pages=5)
    assert p.total == 100
    assert p.pages == 5


def test_paginated_response_generic() -> None:
    p: PaginatedResponse[str] = PaginatedResponse(
        items=["a", "b"],
        pagination=PaginationInfo(total=2, page=1, page_size=10, pages=1),
    )
    assert len(p.items) == 2


def test_health_check_fields() -> None:
    h = HealthCheck(name="database", status="ok")
    assert h.name == "database"
    assert h.status == "ok"


def test_health_response_fields() -> None:
    r = HealthResponse(status="ok", checks=[])
    assert r.status == "ok"


# ─── Workspace schemas ────────────────────────────────────────────────────────


def test_workspace_create_requires_name_and_slug() -> None:
    w = WorkspaceCreate(name="Acme", slug="acme")
    assert w.name == "Acme"
    assert w.slug == "acme"


def test_workspace_create_missing_slug_fails() -> None:
    with pytest.raises(ValidationError):
        WorkspaceCreate(name="Acme")  # type: ignore[call-arg]


def test_workspace_read_has_id_and_timestamps() -> None:
    now = datetime.now(tz=UTC)
    w = WorkspaceRead(
        id=uuid.uuid4(),
        name="Acme",
        slug="acme",
        settings={},
        created_at=now,
        updated_at=now,
    )
    assert isinstance(w.id, uuid.UUID)


def test_workspace_read_from_attributes() -> None:
    """WorkspaceRead must accept ORM objects via model_config from_attributes."""
    from alayaos_core.schemas.workspace import WorkspaceRead

    # from_attributes must be True
    assert WorkspaceRead.model_config.get("from_attributes") is True


def test_workspace_update_all_optional() -> None:
    u = WorkspaceUpdate()  # no fields required
    assert u.name is None
    assert u.settings is None


# ─── Event schemas ────────────────────────────────────────────────────────────


def test_event_create_required_fields() -> None:
    e = EventCreate(source_type="slack", source_id="C123", content={"text": "hi"})
    assert e.source_type == "slack"


def test_event_create_metadata_optional() -> None:
    e = EventCreate(source_type="slack", source_id="C123", content={})
    assert e.metadata is None or isinstance(e.metadata, dict)


def test_event_read_has_all_fields() -> None:
    now = datetime.now(tz=UTC)
    e = EventRead(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        source_type="slack",
        source_id="C123",
        content={"text": "hi"},
        created_at=now,
        updated_at=now,
    )
    assert e.source_type == "slack"


# ─── Entity schemas ───────────────────────────────────────────────────────────


def test_entity_create_required_fields() -> None:
    e = EntityCreate(entity_type_id=uuid.uuid4(), name="Alice")
    assert e.name == "Alice"


def test_entity_create_optional_fields() -> None:
    e = EntityCreate(entity_type_id=uuid.uuid4(), name="Alice")
    assert e.description is None
    assert e.properties == {} or e.properties is None


def test_entity_read_has_external_ids() -> None:
    now = datetime.now(tz=UTC)
    e = EntityRead(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        entity_type_id=uuid.uuid4(),
        name="Alice",
        external_ids=[],
        created_at=now,
        updated_at=now,
    )
    assert e.external_ids == []


def test_entity_update_all_optional() -> None:
    u = EntityUpdate()
    assert u.name is None
    assert u.is_deleted is None


# ─── EntityType schemas ───────────────────────────────────────────────────────


def test_entity_type_create_required_fields() -> None:
    et = EntityTypeCreate(slug="person", display_name="Person")
    assert et.slug == "person"


def test_entity_type_read_has_all_fields() -> None:
    now = datetime.now(tz=UTC)
    et = EntityTypeRead(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        slug="person",
        display_name="Person",
        is_core=False,
        schema_version=1,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    assert et.slug == "person"


# ─── Predicate schemas ────────────────────────────────────────────────────────


def test_predicate_read_has_all_fields() -> None:
    now = datetime.now(tz=UTC)
    p = PredicateRead(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        slug="knows",
        display_name="Knows",
        value_type="entity_ref",
        cardinality="many",
        is_core=False,
        schema_version=1,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    assert p.slug == "knows"


def test_predicate_create_required_fields() -> None:
    p = PredicateCreate(slug="knows", display_name="Knows", value_type="entity_ref")
    assert p.slug == "knows"


# ─── APIKey schemas ───────────────────────────────────────────────────────────


def test_api_key_create_required_fields() -> None:
    k = APIKeyCreate(name="CI key")
    assert k.name == "CI key"


def test_api_key_create_scopes_optional() -> None:
    k = APIKeyCreate(name="CI key")
    assert k.scopes is None or isinstance(k.scopes, list)


def test_api_key_read_no_raw_key() -> None:
    now = datetime.now(tz=UTC)
    k = APIKeyRead(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        name="CI key",
        key_prefix="alaya_",
        scopes=["read"],
        is_bootstrap=False,
        created_at=now,
        updated_at=now,
    )
    # APIKeyRead must NOT have key_hash or raw_key
    assert not hasattr(k, "key_hash")
    assert not hasattr(k, "raw_key")


def test_api_key_create_response_has_raw_key() -> None:
    now = datetime.now(tz=UTC)
    r = APIKeyCreateResponse(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        name="CI key",
        key_prefix="alaya_",
        scopes=["read"],
        is_bootstrap=False,
        raw_key="alaya_secret123",
        created_at=now,
        updated_at=now,
    )
    assert r.raw_key == "alaya_secret123"


# ─── __init__.py ─────────────────────────────────────────────────────────────


def test_schemas_init_exports_main_classes() -> None:
    from alayaos_core import schemas

    expected = [
        "WorkspaceCreate",
        "WorkspaceRead",
        "WorkspaceUpdate",
        "EventCreate",
        "EventRead",
        "EntityCreate",
        "EntityRead",
        "APIKeyCreate",
        "APIKeyRead",
        "APIKeyCreateResponse",
    ]
    for name in expected:
        assert hasattr(schemas, name), f"schemas.__init__ missing: {name}"
