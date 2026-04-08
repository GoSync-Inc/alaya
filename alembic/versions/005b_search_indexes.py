"""Search indexes: HNSW, GIN, pg_trgm

Revision ID: 005b
Revises: 005a
Create Date: 2026-04-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "005b"
down_revision: str | None = "005a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execution_options(isolation_level="AUTOCOMMIT")

    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vc_embedding_hnsw "
        "ON vector_chunks USING hnsw (embedding halfvec_cosine_ops) "
        "WITH (m = 16, ef_construction = 128)"
    )
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vc_tsv ON vector_chunks USING gin(tsv)")
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_entities_tsv ON l1_entities USING gin(tsv)")
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_entities_name_trgm ON l1_entities USING gin(name gin_trgm_ops)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_tree_dirty ON l3_tree_nodes (workspace_id) WHERE is_dirty = true")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_tree_dirty")
    op.execute("DROP INDEX IF EXISTS idx_entities_name_trgm")
    op.execute("DROP INDEX IF EXISTS idx_entities_tsv")
    op.execute("DROP INDEX IF EXISTS idx_vc_tsv")
    op.execute("DROP INDEX IF EXISTS idx_vc_embedding_hnsw")
