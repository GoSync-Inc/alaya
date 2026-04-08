"""Search columns: halfvec, tsvector, tree extensions

Revision ID: 005a
Revises: 004
Create Date: 2026-04-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "005a"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute("ALTER TABLE vector_chunks DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE vector_chunks ADD COLUMN embedding halfvec(1024)")
    op.execute(
        "ALTER TABLE vector_chunks ADD COLUMN tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED"
    )

    op.execute(
        "ALTER TABLE l1_entities ADD COLUMN tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple', coalesce(name, '') || ' ' || coalesce(description, ''))) STORED"
    )

    op.execute("ALTER TABLE l3_tree_nodes ADD COLUMN is_dirty boolean NOT NULL DEFAULT true")
    op.execute("ALTER TABLE l3_tree_nodes ADD COLUMN markdown_cache text")
    op.execute("ALTER TABLE l3_tree_nodes ADD COLUMN last_rebuilt_at timestamptz")
    op.execute("ALTER TABLE l3_tree_nodes ADD COLUMN summary jsonb NOT NULL DEFAULT '{}'")


def downgrade() -> None:
    op.execute("ALTER TABLE l3_tree_nodes DROP COLUMN IF EXISTS summary")
    op.execute("ALTER TABLE l3_tree_nodes DROP COLUMN IF EXISTS last_rebuilt_at")
    op.execute("ALTER TABLE l3_tree_nodes DROP COLUMN IF EXISTS markdown_cache")
    op.execute("ALTER TABLE l3_tree_nodes DROP COLUMN IF EXISTS is_dirty")

    op.execute("ALTER TABLE l1_entities DROP COLUMN IF EXISTS tsv")

    op.execute("ALTER TABLE vector_chunks DROP COLUMN IF EXISTS tsv")
    op.execute("ALTER TABLE vector_chunks DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE vector_chunks ADD COLUMN embedding vector(1536)")
