from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database
    database_url: str

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # OpenAI — default "" so the app starts (and /health works) without a key;
    # the agent will fail with a clear 401 from OpenAI if a run is attempted.
    openai_api_key: str = ""
    agent_model: str = "gpt-4o"

    # App
    environment: str = "development"
    app_version: str = "0.1.0"

    # CORS — comma-separated or JSON list of allowed origins.
    # In production set this to your frontend URL, e.g.:
    #   CORS_ORIGINS=["https://infrapilot-ai.vercel.app"]
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8080",
    ]

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
