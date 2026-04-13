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
    HEALTH_READY_VERBOSE: bool = False
    API_DOCS_ENABLED: bool | None = None
    TRUSTED_HOSTS: list[str] = []

    # LLM Provider
    EXTRACTION_LLM_PROVIDER: str = "anthropic"  # anthropic|openai|ollama|vllm
    ANTHROPIC_API_KEY: SecretStr = SecretStr("")
    ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"

    # LLM Fallback
    LLM_FALLBACK_PROVIDERS: list[str] = []  # e.g. ["fake"] for testing

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

    # Cortex
    CORTEX_CLASSIFIER_MODEL: str = "claude-haiku-4-5-20251001"
    CORTEX_MAX_CHUNK_TOKENS: int = 3000
    CORTEX_CRYSTAL_THRESHOLD: float = 0.1  # Very low for max recall (charter non-negotiable)
    CORTEX_TRUNCATION_TOKENS: int = 800

    # Crystallizer
    CRYSTALLIZER_MODEL: str = "claude-sonnet-4-6-20250514"
    CRYSTALLIZER_CONFIDENCE_HIGH: float = 0.8  # Spec: high tier >= 0.8
    CRYSTALLIZER_CONFIDENCE_LOW: float = 0.6  # Spec: medium tier >= 0.6, low < 0.6

    # Integrator
    INTEGRATOR_MODEL: str = "claude-sonnet-4-6-20250514"
    INTEGRATOR_BATCH_SIZE: int = 20
    INTEGRATOR_DIRTY_SET_THRESHOLD: int = 10
    INTEGRATOR_MAX_WAIT_SECONDS: int = 1800
    INTEGRATOR_STUCK_RUN_SECONDS: int = 900
    INTEGRATOR_WINDOW_HOURS: int = 48
    INTEGRATOR_DEDUP_THRESHOLD: float = 0.85
    INTEGRATOR_DEDUP_AMBIGUOUS_LOW: float = 0.70

    # Embedding
    EMBEDDING_MODEL: str = "intfloat/multilingual-e5-large"
    EMBEDDING_DIMENSIONS: int = 1024
    EMBEDDING_BATCH_SIZE: int = 64

    # Search
    SEARCH_HNSW_EF_SEARCH: int = 100
    SEARCH_RRF_K: int = 60
    SEARCH_MAX_RESULTS: int = 20
    SEARCH_DEFAULT_LIMIT: int = 10

    # Q&A (Ask)
    ASK_MODEL: str = "claude-sonnet-4-6-20250514"
    ASK_MAX_CONTEXT_TOKENS: int = 8192
    ASK_MAX_OUTPUT_TOKENS: int = 2048
    ASK_MAX_RESULTS_FOR_LLM: int = 10
    ASK_RATE_LIMIT_PER_MINUTE: int = 10
    ASK_RATE_LIMIT_PER_HOUR: int = 100

    # Knowledge Tree
    TREE_BRIEFING_MODEL: str = "claude-sonnet-4-6-20250514"
    TREE_BRIEFING_CACHE_TTL: int = 900  # 15 minutes
    TREE_MAX_DEPTH: int = 10
    TREE_MAX_CLAIMS_PER_BRIEF: int = 50

    # Feature flags
    FEATURE_FLAG_USE_CORTEX: bool = True  # Cortex pipeline enabled (FakeLLM returns realistic DomainScores)
    FEATURE_FLAG_VECTOR_SEARCH: bool = False  # Enable after embedding backfill
