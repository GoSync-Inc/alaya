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
