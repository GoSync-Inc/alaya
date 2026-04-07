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
