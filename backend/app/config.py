from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database
    database_url: str

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # OpenAI
    openai_api_key: str
    agent_model: str = "gpt-4o"

    # App
    environment: str = "development"
    app_version: str = "0.1.0"

    # Log backend — "postgres" (MVP) | "loki" (v1.5 optional extension)
    log_backend: str = "postgres"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


# Single shared instance — import this everywhere
settings = Settings()
