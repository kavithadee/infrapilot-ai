import json

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8080",
]


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

    # CORS — accepts a JSON array or a comma-separated string.
    # In production set this to your frontend URL, e.g.:
    #   CORS_ORIGINS=https://infrapilot-ai.vercel.app
    #   CORS_ORIGINS=["https://infrapilot-ai.vercel.app","http://localhost:8080"]
    # If unset or empty the localhost defaults are used.
    cors_origins: list[str] = _DEFAULT_CORS_ORIGINS

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: object) -> list[str]:
        if not v:
            return _DEFAULT_CORS_ORIGINS
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return _DEFAULT_CORS_ORIGINS
            # Try JSON array first: ["https://..."]
            if v.startswith("["):
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return [str(o).strip() for o in parsed if o]
                except json.JSONDecodeError:
                    pass
            # Fall back to comma-separated: https://foo.com,https://bar.com
            return [o.strip() for o in v.split(",") if o.strip()]
        return _DEFAULT_CORS_ORIGINS

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
