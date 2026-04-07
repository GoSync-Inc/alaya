from pydantic import SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "ALAYA_"}

    DATABASE_URL: str = "postgresql+asyncpg://alaya:alaya@localhost:5432/alaya"
    REDIS_URL: str = "redis://localhost:6379/0"
    ENV: str = "dev"  # dev | production
    SECRET_KEY: SecretStr = SecretStr("change-me-in-production")

    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE: int = 300
    DB_POOL_TIMEOUT: int = 30
    DB_ECHO: bool = False
    LOG_LEVEL: str = "INFO"

    # LLM Provider
    EXTRACTION_LLM_PROVIDER: str = "anthropic"  # anthropic|openai|ollama|vllm
    ANTHROPIC_API_KEY: SecretStr = SecretStr("")
    ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"

    # Extraction Pipeline
    EXTRACTION_MAX_INPUT_CHARS: int = 100_000
    EXTRACTION_GLEANING_MIN_TOKENS: int = 2000
    EXTRACTION_MAX_ENTITIES_PER_EVENT: int = 50
    EXTRACTION_MAX_CLAIMS_PER_ENTITY: int = 100

    # Entity Resolution
    ENTITY_RESOLUTION_AUTO_MERGE_THRESHOLD: float = 0.92
    ENTITY_RESOLUTION_POSSIBLE_MATCH_THRESHOLD: float = 0.85

    # Worker (TaskIQ)
    WORKER_CONCURRENCY: int = 4
    WORKER_EXTRACT_TIMEOUT: int = 120
    WORKER_WRITE_TIMEOUT: int = 60
    WORKER_ENRICH_TIMEOUT: int = 60
    WORKER_LOCK_TIMEOUT: int = 30
