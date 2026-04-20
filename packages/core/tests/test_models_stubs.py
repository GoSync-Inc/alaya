"""Tests for stub SQLAlchemy models (Task 3 & 4)."""

from sqlalchemy import inspect

from alayaos_core.models.acl import (
    AccessGroup,
    AccessGroupMember,
    ResourceGrant,
    WorkspaceMember,
)
from alayaos_core.models.audit import AuditLog
from alayaos_core.models.claim import ClaimSource, L2Claim
from alayaos_core.models.entity import L1Entity
from alayaos_core.models.relation import L1Relation, RelationSource
from alayaos_core.models.tree import L3TreeNode
from alayaos_core.models.vector import VectorChunk

# ─── L1Relation ──────────────────────────────────────────────────────────────


def test_l1_relation_tablename() -> None:
    assert L1Relation.__tablename__ == "l1_relations"


def test_l1_relation_columns() -> None:
    mapper = inspect(L1Relation)
    cols = {c.key for c in mapper.columns}
    assert {
        "id",
        "workspace_id",
        "source_entity_id",
        "target_entity_id",
        "relation_type",
        "confidence",
        "extraction_run_id",
        "created_at",
        "updated_at",
    }.issubset(cols)


def test_l1_relation_source_fk() -> None:
    mapper = inspect(L1Relation)
    col = mapper.columns["source_entity_id"]
    fks = list(col.foreign_keys)
    assert any("l1_entities.id" in str(fk) for fk in fks)


def test_l1_relation_target_fk() -> None:
    mapper = inspect(L1Relation)
    col = mapper.columns["target_entity_id"]
    fks = list(col.foreign_keys)
    assert any("l1_entities.id" in str(fk) for fk in fks)


def test_relation_source_tablename() -> None:
    assert RelationSource.__tablename__ == "relation_sources"


def test_relation_source_has_workspace_id() -> None:
    mapper = inspect(RelationSource)
    cols = {c.key for c in mapper.columns}
    assert "workspace_id" in cols


def test_relation_source_columns() -> None:
    mapper = inspect(RelationSource)
    cols = {c.key for c in mapper.columns}
    assert {"id", "workspace_id", "relation_id", "event_id", "created_at"}.issubset(cols)


# ─── L2Claim ─────────────────────────────────────────────────────────────────


def test_l2_claim_tablename() -> None:
    assert L2Claim.__tablename__ == "l2_claims"


def test_l2_claim_columns() -> None:
    mapper = inspect(L2Claim)
    cols = {c.key for c in mapper.columns}
    assert {
        "id",
        "workspace_id",
        "entity_id",
        "predicate",
        "predicate_id",
        "value",
        "confidence",
        "valid_from",
        "valid_to",
        "source_event_id",
        "status",
        "observed_at",
        "supersedes",
        "source_summary",
        "value_type",
        "extraction_run_id",
        "created_at",
        "updated_at",
    }.issubset(cols)


def test_l2_claim_predicate_id_fk() -> None:
    mapper = inspect(L2Claim)
    col = mapper.columns["predicate_id"]
    fks = list(col.foreign_keys)
    assert any("predicate_definitions.id" in str(fk) for fk in fks)
    assert col.nullable is True


def test_l2_claim_extraction_run_composite_fk() -> None:
    from sqlalchemy import ForeignKeyConstraint

    table = L2Claim.__table__
    composite_fks = [c for c in table.constraints if isinstance(c, ForeignKeyConstraint)]
    fk_targets = {str(e) for c in composite_fks for e in c.elements}
    assert any("extraction_runs" in t for t in fk_targets)


def test_l1_relation_extraction_run_composite_fk() -> None:
    from sqlalchemy import ForeignKeyConstraint

    table = L1Relation.__table__
    composite_fks = [c for c in table.constraints if isinstance(c, ForeignKeyConstraint)]
    fk_targets = {str(e) for c in composite_fks for e in c.elements}
    assert any("extraction_runs" in t for t in fk_targets)


def test_claim_source_tablename() -> None:
    assert ClaimSource.__tablename__ == "claim_sources"


def test_claim_source_has_workspace_id() -> None:
    mapper = inspect(ClaimSource)
    cols = {c.key for c in mapper.columns}
    assert "workspace_id" in cols


def test_claim_source_columns() -> None:
    mapper = inspect(ClaimSource)
    cols = {c.key for c in mapper.columns}
    assert {"id", "workspace_id", "claim_id", "event_id", "created_at"}.issubset(cols)


# ─── L1Entity tsvector ───────────────────────────────────────────────────────


def test_l1_entity_tsv_column() -> None:
    """tsv column must be present on L1Entity."""
    mapper = inspect(L1Entity)
    cols = {c.key for c in mapper.columns}
    assert "tsv" in cols


# ─── L3TreeNode ──────────────────────────────────────────────────────────────


def test_l3_tree_node_tablename() -> None:
    assert L3TreeNode.__tablename__ == "l3_tree_nodes"


def test_l3_tree_node_columns() -> None:
    mapper = inspect(L3TreeNode)
    cols = {c.key for c in mapper.columns}
    assert {
        "id",
        "workspace_id",
        "path",
        "node_type",
        "entity_id",
        "content",
        "sort_order",
        "created_at",
        "updated_at",
    }.issubset(cols)


def test_l3_tree_node_has_unique_constraint() -> None:
    table = L3TreeNode.__table__
    unique_constraints = [c for c in table.constraints if hasattr(c, "columns") and len(c.columns) >= 2]
    assert len(unique_constraints) >= 1


# ─── VectorChunk ─────────────────────────────────────────────────────────────


def test_l3_tree_node_new_columns() -> None:
    mapper = inspect(L3TreeNode)
    cols = {c.key for c in mapper.columns}
    assert {"is_dirty", "markdown_cache", "last_rebuilt_at", "summary"}.issubset(cols)


def test_l3_tree_node_is_dirty_not_nullable() -> None:
    mapper = inspect(L3TreeNode)
    col = mapper.columns["is_dirty"]
    assert col.nullable is False


# ─── VectorChunk ─────────────────────────────────────────────────────────────


def test_vector_chunk_tablename() -> None:
    assert VectorChunk.__tablename__ == "vector_chunks"


def test_vector_chunk_columns() -> None:
    mapper = inspect(VectorChunk)
    cols = {c.key for c in mapper.columns}
    assert {
        "id",
        "workspace_id",
        "source_type",
        "source_id",
        "chunk_index",
        "content",
        "embedding",
        "created_at",
    }.issubset(cols)


def test_vector_chunk_tsv_column() -> None:
    """tsv column must be present and server-generated."""
    mapper = inspect(VectorChunk)
    cols = {c.key for c in mapper.columns}
    assert "tsv" in cols


def test_vector_chunk_embedding_column() -> None:
    """embedding column must exist and use pgvector HALFVEC type with 1024 dims."""
    from pgvector.sqlalchemy import HALFVEC

    mapper = inspect(VectorChunk)
    col = mapper.columns["embedding"]
    assert isinstance(col.type, HALFVEC)
    assert col.type.dim == 1024


# ─── AuditLog ─────────────────────────────────────────────────────────────────


def test_audit_log_tablename() -> None:
    assert AuditLog.__tablename__ == "audit_log"


def test_audit_log_columns() -> None:
    mapper = inspect(AuditLog)
    cols = {c.key for c in mapper.columns}
    assert {
        "id",
        "workspace_id",
        "actor_type",
        "actor_id",
        "action",
        "resource_type",
        "resource_id",
        "changes",
        "ip_address",
        "created_at",
    }.issubset(cols)


def test_audit_log_has_no_updated_at() -> None:
    """AuditLog is immutable — must NOT have updated_at."""
    mapper = inspect(AuditLog)
    cols = {c.key for c in mapper.columns}
    assert "updated_at" not in cols


# ─── ACL models ──────────────────────────────────────────────────────────────


def test_workspace_member_tablename() -> None:
    assert WorkspaceMember.__tablename__ == "workspace_members"


def test_workspace_member_columns() -> None:
    mapper = inspect(WorkspaceMember)
    cols = {c.key for c in mapper.columns}
    assert {
        "id",
        "workspace_id",
        "user_id",
        "role",
        "joined_at",
        "created_at",
        "updated_at",
    }.issubset(cols)


def test_workspace_member_unique_constraint() -> None:
    table = WorkspaceMember.__table__
    unique_constraints = [c for c in table.constraints if hasattr(c, "columns") and len(c.columns) >= 2]
    assert len(unique_constraints) >= 1


def test_access_group_tablename() -> None:
    assert AccessGroup.__tablename__ == "access_groups"


def test_access_group_columns() -> None:
    mapper = inspect(AccessGroup)
    cols = {c.key for c in mapper.columns}
    assert {
        "id",
        "workspace_id",
        "name",
        "description",
        "created_at",
        "updated_at",
    }.issubset(cols)


def test_access_group_unique_constraint() -> None:
    table = AccessGroup.__table__
    unique_constraints = [c for c in table.constraints if hasattr(c, "columns") and len(c.columns) >= 2]
    assert len(unique_constraints) >= 1


def test_access_group_member_tablename() -> None:
    assert AccessGroupMember.__tablename__ == "access_group_members"


def test_access_group_member_has_workspace_id() -> None:
    mapper = inspect(AccessGroupMember)
    cols = {c.key for c in mapper.columns}
    assert "workspace_id" in cols


def test_access_group_member_columns() -> None:
    mapper = inspect(AccessGroupMember)
    cols = {c.key for c in mapper.columns}
    assert {"id", "workspace_id", "group_id", "member_id", "created_at"}.issubset(cols)


def test_resource_grant_tablename() -> None:
    assert ResourceGrant.__tablename__ == "resource_grants"


def test_resource_grant_columns() -> None:
    mapper = inspect(ResourceGrant)
    cols = {c.key for c in mapper.columns}
    assert {
        "id",
        "workspace_id",
        "grantee_type",
        "grantee_id",
        "resource_type",
        "resource_id",
        "permission",
        "created_at",
    }.issubset(cols)


# ─── __init__.py imports ─────────────────────────────────────────────────────


def test_models_init_exports_all() -> None:
    """models/__init__.py must export all model classes."""
    from alayaos_core import models

    expected = [
        "Base",
        "Workspace",
        "L0Event",
        "EntityTypeDefinition",
        "PredicateDefinition",
        "L1Entity",
        "EntityExternalId",
        "APIKey",
        "L1Relation",
        "RelationSource",
        "L2Claim",
        "ClaimSource",
        "L3TreeNode",
        "VectorChunk",
        "AuditLog",
        "WorkspaceMember",
        "AccessGroup",
        "AccessGroupMember",
        "ResourceGrant",
        "ExtractionRun",
    ]
    for name in expected:
        assert hasattr(models, name), f"models.__init__ missing: {name}"
