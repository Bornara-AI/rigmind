from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings read from env vars (case-insensitive), e.g. ENVIRONMENT."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "RigMind AI Service"
    environment: str = "local"
    database_url: str | None = None
    openai_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
