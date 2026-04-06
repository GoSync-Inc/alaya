"""Initial schema — 18 tables with RLS and composite FK

Revision ID: 001
Revises:
Create Date: 2026-04-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --------------------------------------------------------------------------
    # 1. Extensions
    # --------------------------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --------------------------------------------------------------------------
    # 2. Tables — dependency order
    # --------------------------------------------------------------------------

    # 1. workspaces (no FK deps)
    op.create_table(
        "workspaces",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("settings", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("slug", name="uq_workspaces_slug"),
    )

    # 2. entity_type_definitions (FK → workspaces)
    op.create_table(
        "entity_type_definitions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.Text(), nullable=True),
        sa.Column("color", sa.Text(), nullable=True),
        sa.Column("is_core", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "id", name="uq_entity_type_ws_id"),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_entity_type_ws_slug"),
    )

    # 3. predicate_definitions (FK → workspaces)
    op.create_table(
        "predicate_definitions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("value_type", sa.Text(), nullable=False, server_default=sa.text("'text'")),
        sa.Column("domain_types", ARRAY(sa.Text()), nullable=True),
        sa.Column("cardinality", sa.Text(), nullable=False, server_default=sa.text("'many'")),
        sa.Column("inverse_slug", sa.Text(), nullable=True),
        sa.Column("is_core", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "id", name="uq_predicate_ws_id"),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_predicate_ws_slug"),
    )

    # 4. l0_events (FK → workspaces)
    op.create_table(
        "l0_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("content", JSONB, nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "id", name="uq_l0_events_ws_id"),
        sa.UniqueConstraint("workspace_id", "source_type", "source_id", name="uq_l0_events_ws_src"),
    )

    # 5. l1_entities (FK → workspaces, entity_type_definitions composite)
    op.create_table(
        "l1_entities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("entity_type_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("properties", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "id", name="uq_l1_entities_ws_id"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "entity_type_id"],
            ["entity_type_definitions.workspace_id", "entity_type_definitions.id"],
            name="fk_entities_type",
        ),
    )

    # 6. entity_external_ids (FK → workspaces, l1_entities composite)
    op.create_table(
        "entity_external_ids",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "entity_id", "source_type", "external_id", name="uq_entity_ext_id"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "entity_id"],
            ["l1_entities.workspace_id", "l1_entities.id"],
            name="fk_ext_id_entity",
        ),
    )

    # 7. api_keys (FK → workspaces)
    op.create_table(
        "api_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("key_prefix", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("scopes", ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{read,write}'")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_bootstrap", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "id", name="uq_api_keys_ws_id"),
        sa.UniqueConstraint("key_prefix", name="uq_api_keys_prefix"),
    )

    # 8. l1_relations (FK → workspaces, l1_entities composite x2)
    op.create_table(
        "l1_relations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("source_entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("target_entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("relation_type", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("1.0")),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "id", name="uq_l1_relations_ws_id"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_entity_id"],
            ["l1_entities.workspace_id", "l1_entities.id"],
            name="fk_relation_source_entity",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "target_entity_id"],
            ["l1_entities.workspace_id", "l1_entities.id"],
            name="fk_relation_target_entity",
        ),
    )

    # 9. relation_sources (join table: FK → l1_relations, l0_events)
    op.create_table(
        "relation_sources",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("relation_id", UUID(as_uuid=True), sa.ForeignKey("l1_relations.id"), nullable=False),
        sa.Column("event_id", UUID(as_uuid=True), sa.ForeignKey("l0_events.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # 10. l2_claims (FK → workspaces, l1_entities composite, predicate_definitions composite, l0_events)
    op.create_table(
        "l2_claims",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("predicate", sa.Text(), nullable=False),
        sa.Column("predicate_id", UUID(as_uuid=True), nullable=True),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("1.0")),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_event_id", UUID(as_uuid=True), sa.ForeignKey("l0_events.id"), nullable=True),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "id", name="uq_l2_claims_ws_id"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "entity_id"],
            ["l1_entities.workspace_id", "l1_entities.id"],
            name="fk_claim_entity",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "predicate_id"],
            ["predicate_definitions.workspace_id", "predicate_definitions.id"],
            name="fk_claim_predicate",
        ),
    )

    # 11. claim_sources (join table: FK → l2_claims, l0_events)
    op.create_table(
        "claim_sources",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("claim_id", UUID(as_uuid=True), sa.ForeignKey("l2_claims.id"), nullable=False),
        sa.Column("event_id", UUID(as_uuid=True), sa.ForeignKey("l0_events.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # 12. l3_tree_nodes (FK → workspaces, l1_entities)
    op.create_table(
        "l3_tree_nodes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("node_type", sa.Text(), nullable=False),
        sa.Column("entity_id", UUID(as_uuid=True), sa.ForeignKey("l1_entities.id"), nullable=True),
        sa.Column("content", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "path", name="uq_tree_node_ws_path"),
    )

    # 13. vector_chunks (FK → workspaces) — embedding added via ALTER TABLE
    op.create_table(
        "vector_chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_id", UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.execute("ALTER TABLE vector_chunks ADD COLUMN embedding vector(1536)")

    # 14. audit_log (FK → workspaces)
    op.create_table(
        "audit_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("resource_id", UUID(as_uuid=True), nullable=True),
        sa.Column("changes", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # 15. workspace_members (FK → workspaces)
    op.create_table(
        "workspace_members",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default=sa.text("'member'")),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "id", name="uq_workspace_members_ws_id"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),
    )

    # 16. access_groups (FK → workspaces)
    op.create_table(
        "access_groups",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "id", name="uq_access_groups_ws_id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_access_group_ws_name"),
    )

    # 17. access_group_members (join table: FK → access_groups, workspace_members)
    op.create_table(
        "access_group_members",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("group_id", UUID(as_uuid=True), sa.ForeignKey("access_groups.id"), nullable=False),
        sa.Column("member_id", UUID(as_uuid=True), sa.ForeignKey("workspace_members.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # 18. resource_grants (FK → workspaces)
    op.create_table(
        "resource_grants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("grantee_type", sa.Text(), nullable=False),
        sa.Column("grantee_id", UUID(as_uuid=True), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("resource_id", UUID(as_uuid=True), nullable=True),
        sa.Column("permission", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --------------------------------------------------------------------------
    # 3. RLS policies — 14 workspace-scoped tables
    # --------------------------------------------------------------------------

    # Standard workspace isolation policy template
    _rls_tables = [
        "l0_events",
        "entity_type_definitions",
        "predicate_definitions",
        "l1_entities",
        "entity_external_ids",
        "l1_relations",
        "l2_claims",
        "l3_tree_nodes",
        "vector_chunks",
        "api_keys",
        "workspace_members",
        "access_groups",
        "resource_grants",
    ]

    for table in _rls_tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY workspace_isolation ON {table} "
            "USING (workspace_id = current_setting('app.workspace_id', true)::uuid)"
        )

    # audit_log: SELECT + INSERT only (no UPDATE/DELETE)
    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_log FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY audit_select ON audit_log FOR SELECT "
        "USING (workspace_id = current_setting('app.workspace_id', true)::uuid)"
    )
    op.execute(
        "CREATE POLICY audit_insert ON audit_log FOR INSERT "
        "WITH CHECK (workspace_id = current_setting('app.workspace_id', true)::uuid)"
    )

    # --------------------------------------------------------------------------
    # 4. Pagination indexes (spec 4.3)
    # --------------------------------------------------------------------------
    op.execute("CREATE INDEX idx_l0_events_pagination ON l0_events(workspace_id, created_at DESC, id DESC)")
    op.execute("CREATE INDEX idx_l1_entities_pagination ON l1_entities(workspace_id, created_at DESC, id DESC)")
    op.execute(
        "CREATE INDEX idx_entity_type_definitions_pagination "
        "ON entity_type_definitions(workspace_id, created_at DESC, id DESC)"
    )
    op.execute(
        "CREATE INDEX idx_predicate_definitions_pagination "
        "ON predicate_definitions(workspace_id, created_at DESC, id DESC)"
    )
    op.execute("CREATE INDEX idx_api_keys_pagination ON api_keys(workspace_id, created_at DESC, id DESC)")
    op.execute("CREATE INDEX idx_workspaces_pagination ON workspaces(created_at DESC, id DESC)")
    op.execute("CREATE UNIQUE INDEX idx_api_keys_prefix ON api_keys(key_prefix)")


def downgrade() -> None:
    # --------------------------------------------------------------------------
    # Drop pagination indexes
    # --------------------------------------------------------------------------
    op.execute("DROP INDEX IF EXISTS idx_api_keys_prefix")
    op.execute("DROP INDEX IF EXISTS idx_workspaces_pagination")
    op.execute("DROP INDEX IF EXISTS idx_api_keys_pagination")
    op.execute("DROP INDEX IF EXISTS idx_predicate_definitions_pagination")
    op.execute("DROP INDEX IF EXISTS idx_entity_type_definitions_pagination")
    op.execute("DROP INDEX IF EXISTS idx_l1_entities_pagination")
    op.execute("DROP INDEX IF EXISTS idx_l0_events_pagination")

    # --------------------------------------------------------------------------
    # Drop RLS policies
    # --------------------------------------------------------------------------
    op.execute("DROP POLICY IF EXISTS audit_insert ON audit_log")
    op.execute("DROP POLICY IF EXISTS audit_select ON audit_log")
    op.execute("ALTER TABLE audit_log DISABLE ROW LEVEL SECURITY")

    _rls_tables = [
        "resource_grants",
        "access_groups",
        "workspace_members",
        "api_keys",
        "vector_chunks",
        "l3_tree_nodes",
        "l2_claims",
        "l1_relations",
        "entity_external_ids",
        "l1_entities",
        "predicate_definitions",
        "entity_type_definitions",
        "l0_events",
    ]
    for table in _rls_tables:
        op.execute(f"DROP POLICY IF EXISTS workspace_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # --------------------------------------------------------------------------
    # Drop tables — reverse dependency order
    # --------------------------------------------------------------------------
    op.drop_table("resource_grants")
    op.drop_table("access_group_members")
    op.drop_table("access_groups")
    op.drop_table("workspace_members")
    op.drop_table("audit_log")
    op.drop_table("vector_chunks")
    op.drop_table("l3_tree_nodes")
    op.drop_table("claim_sources")
    op.drop_table("l2_claims")
    op.drop_table("relation_sources")
    op.drop_table("l1_relations")
    op.drop_table("entity_external_ids")
    op.drop_table("l1_entities")
    op.drop_table("api_keys")
    op.drop_table("l0_events")
    op.drop_table("predicate_definitions")
    op.drop_table("entity_type_definitions")
    op.drop_table("workspaces")

    # --------------------------------------------------------------------------
    # Drop extensions
    # --------------------------------------------------------------------------
    op.execute("DROP EXTENSION IF EXISTS vector")
