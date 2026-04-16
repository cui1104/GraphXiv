from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql://app:changeme@postgres:5432/papers"
    redis_url: str = "redis://redis:6379/0"
    postgres_user: str = "app"
    postgres_password: str = "changeme"
    postgres_db: str = "papers"
    data_dir: str = "/data"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
