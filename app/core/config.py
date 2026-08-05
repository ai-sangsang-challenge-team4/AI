from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TeacherHub Backend"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"

    database_url: str
    llm_api_key: str = ""
    llm_model: str = ""
    llm_temperature: float = 0

    prompt_version: str = "risk-tag-prompt-v0.1"
    rule_version: str = "risk-rule-v0.1"

    rag_top_k: int = 5
    rag_index_version: str = "policy-index-v0.1"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()