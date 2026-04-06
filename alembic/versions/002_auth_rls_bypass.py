"""Auth RLS bypass — remove FORCE on api_keys, add health check functions

Revision ID: 002
Revises: 001
Create Date: 2026-04-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # api_keys: remove FORCE so the table owner (application role) can query
    # without workspace context. RLS still applies to non-owner roles.
    op.execute("ALTER TABLE api_keys NO FORCE ROW LEVEL SECURITY")

    # Health check functions — SECURITY DEFINER bypasses RLS for global counts
    op.execute("""
        CREATE OR REPLACE FUNCTION check_core_seeds() RETURNS bigint AS $$
            SELECT count(*) FROM entity_type_definitions WHERE is_core = true;
        $$ LANGUAGE sql SECURITY DEFINER
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION check_user_api_keys() RETURNS bigint AS $$
            SELECT count(*) FROM api_keys WHERE is_bootstrap = false;
        $$ LANGUAGE sql SECURITY DEFINER
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS check_user_api_keys()")
    op.execute("DROP FUNCTION IF EXISTS check_core_seeds()")
    op.execute("ALTER TABLE api_keys FORCE ROW LEVEL SECURITY")
