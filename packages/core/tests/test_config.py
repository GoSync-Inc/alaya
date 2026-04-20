"""Tests for Settings config module (Task 6)."""

import pytest

from alayaos_core.config import Settings


def test_settings_has_database_url() -> None:
    from pydantic import SecretStr

    s = Settings()
    assert isinstance(s.DATABASE_URL, SecretStr)
    assert "postgresql+asyncpg" in s.DATABASE_URL.get_secret_value()
    # SecretStr must hide the value in repr/str.
    assert "postgresql" not in str(s.DATABASE_URL)


def test_settings_has_redis_url() -> None:
    from pydantic import SecretStr

    s = Settings()
    assert isinstance(s.REDIS_URL, SecretStr)
    assert "redis://" in s.REDIS_URL.get_secret_value()
    assert "redis" not in str(s.REDIS_URL)


def test_settings_env_default() -> None:
    s = Settings()
    assert s.ENV == "dev"


def test_settings_secret_key_is_secret_str() -> None:
    from pydantic import SecretStr

    s = Settings()
    assert isinstance(s.SECRET_KEY, SecretStr)


def test_settings_secret_key_not_plain_text() -> None:
    """SecretStr must not expose value via str()."""
    s = Settings()
    assert "change-me" not in str(s.SECRET_KEY)


def test_settings_env_prefix() -> None:
    """model_config must have env_prefix ALAYA_."""
    s = Settings()
    assert s.model_config.get("env_prefix") == "ALAYA_"


def test_settings_has_extraction_config() -> None:
    s = Settings()
    assert s.EXTRACTION_LLM_PROVIDER == "anthropic"
    assert s.EXTRACTION_MAX_INPUT_CHARS == 100_000


def test_settings_has_entity_resolution_thresholds() -> None:
    s = Settings()
    assert s.ENTITY_RESOLUTION_AUTO_MERGE_THRESHOLD == 0.92
    assert s.ENTITY_RESOLUTION_POSSIBLE_MATCH_THRESHOLD == 0.85


def test_settings_anthropic_key_is_secret() -> None:
    from pydantic import SecretStr

    s = Settings()
    assert isinstance(s.ANTHROPIC_API_KEY, SecretStr)


def test_settings_worker_config() -> None:
    s = Settings()
    assert s.WORKER_CONCURRENCY == 4
    assert s.WORKER_EXTRACT_TIMEOUT == 120


def test_settings_embedding_config() -> None:
    s = Settings()
    assert s.EMBEDDING_MODEL == "intfloat/multilingual-e5-large"
    assert s.EMBEDDING_DIMENSIONS == 1024
    assert s.EMBEDDING_BATCH_SIZE == 64


def test_settings_search_config() -> None:
    s = Settings()
    assert s.SEARCH_HNSW_EF_SEARCH == 100
    assert s.SEARCH_RRF_K == 60
    assert s.SEARCH_MAX_RESULTS == 20
    assert s.SEARCH_DEFAULT_LIMIT == 10


def test_settings_ask_config() -> None:
    s = Settings()
    assert s.ASK_MODEL == "claude-sonnet-4-6"
    assert s.ASK_MAX_CONTEXT_TOKENS == 8192
    assert s.ASK_MAX_OUTPUT_TOKENS == 2048
    assert s.ASK_MAX_RESULTS_FOR_LLM == 10
    assert s.ASK_RATE_LIMIT_PER_MINUTE == 10
    assert s.ASK_RATE_LIMIT_PER_HOUR == 100


def test_settings_tree_config() -> None:
    s = Settings()
    assert s.TREE_BRIEFING_MODEL == "claude-sonnet-4-6"
    assert s.TREE_BRIEFING_CACHE_TTL == 900
    assert s.TREE_MAX_DEPTH == 10
    assert s.TREE_MAX_CLAIMS_PER_BRIEF == 50


def test_settings_feature_flag_vector_search() -> None:
    s = Settings()
    assert s.FEATURE_FLAG_VECTOR_SEARCH is False


@pytest.mark.parametrize(
    ("env_value", "docs_value", "expected"),
    [
        ("dev", None, None),
        ("production", None, None),
        ("production", "true", True),
        ("production", "false", False),
    ],
)
def test_settings_security_hardening_flags(monkeypatch, env_value: str, docs_value: str | None, expected) -> None:
    monkeypatch.setenv("ALAYA_ENV", env_value)
    if docs_value is None:
        monkeypatch.delenv("ALAYA_API_DOCS_ENABLED", raising=False)
    else:
        monkeypatch.setenv("ALAYA_API_DOCS_ENABLED", docs_value)
    monkeypatch.setenv("ALAYA_TRUSTED_HOSTS", '["api.example.com","testserver"]')

    s = Settings()

    assert s.API_DOCS_ENABLED is expected
    assert s.TRUSTED_HOSTS == ["api.example.com", "testserver"]
