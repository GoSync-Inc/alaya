from pydantic import SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "ALAYA_"}

    DATABASE_URL: str = "postgresql+asyncpg://alaya:alaya@localhost:5432/alaya"
    REDIS_URL: str = "redis://localhost:6379/0"
    ENV: str = "dev"  # dev | production
    SECRET_KEY: SecretStr = SecretStr("change-me-in-production")
