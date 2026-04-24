"""Run 6.2 operator and CI rollout checks."""

from pathlib import Path


def test_docker_init_pins_pgvector_080() -> None:
    init_sql = Path("docker/init-db.sql").read_text()

    assert "CREATE EXTENSION IF NOT EXISTS vector VERSION '0.8.0';" in init_sql


def test_ci_integration_job_smokes_pgvector_08_or_newer() -> None:
    ci = Path(".github/workflows/ci.yml").read_text()

    assert "name: Verify pgvector >=0.8" in ci
    assert "pgvector/pgvector:pg17" in ci
    assert "CREATE EXTENSION IF NOT EXISTS vector" in ci
    assert "pgvector >=0.8" in ci


def test_run62_changelog_has_required_operator_bullets() -> None:
    changelog = Path("docs/CHANGELOG-run6.2.md").read_text().lower()

    required = [
        "restricted and private events now extract",
        "claim.value.iso can be null",
        "pgvector >=0.8 required",
        "backfill_restricted_extraction.py",
        "non-admin /tree bypasses cache",
        "for update skip locked",
        "duplicate enqueue",
    ]
    for phrase in required:
        assert phrase in changelog


def test_run62_docs_state_fall_closed_vector_access_defaults() -> None:
    """Operator docs must say vector access falls closed when provenance is missing."""
    changelog = Path("docs/CHANGELOG-run6.2.md").read_text().lower()
    llms = Path("llms.txt").read_text().lower()

    for doc in (changelog, llms):
        assert "fall-closed" in doc
        assert "vector_chunks.access_level" in doc
        assert "restricted" in doc


def test_run62_changelog_mentions_admin_flags_added_by_s3() -> None:
    """Run 6.2 docs must not claim /admin/flags is absent."""
    changelog = Path("docs/CHANGELOG-run6.2.md").read_text()

    assert "GET /admin/flags" in changelog
    assert "S3" in changelog
    assert "does not add a runtime `/admin/flags` endpoint" not in changelog


def test_deployment_docs_require_migration_008_before_workers() -> None:
    """Runbook must protect workers that depend on migration 008 helper functions."""
    deployment = Path("docs/deployment.md").read_text()

    assert "migration 008" in deployment.lower()
    assert "API workers" in deployment
    assert "tier_rank" in deployment
    assert "rank_to_level" in deployment
