"""Tests for Settings config module (Task 6)."""

from alayaos_core.config import Settings


def test_settings_has_database_url() -> None:
    s = Settings()
    assert "postgresql+asyncpg" in s.DATABASE_URL


def test_settings_has_redis_url() -> None:
    s = Settings()
    assert "redis://" in s.REDIS_URL


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
