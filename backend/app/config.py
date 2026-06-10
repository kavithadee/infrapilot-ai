import json

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_CORS = "http://localhost:3000,http://localhost:5173,http://localhost:8080"


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

    # CORS — stored as a plain string so pydantic-settings never tries to
    # JSON-parse it (which crashes on comma-separated values or empty strings).
    # Accepts comma-separated URLs or a JSON array; parsed via cors_origins_list.
    # Examples:
    #   CORS_ORIGINS=https://infrapilot-ai.vercel.app
    #   CORS_ORIGINS=https://foo.vercel.app,http://localhost:8080
    #   CORS_ORIGINS=["https://foo.vercel.app"]
    cors_origins: str = _DEFAULT_CORS

    # Log backend — "postgres" (MVP)
    log_backend: str = "postgres"

    # GitHub MCP integration (v1.6 remediation feature)
    # Fine-grained PAT with Contents + Pull requests (read/write) on the target repo only.
    # App starts without these set; the remediation endpoint returns 503 if github_token is empty.
    github_token: str = Field(
        default="",
        validation_alias="GITHUB_PERSONAL_ACCESS_TOKEN",
    )
    github_target_repo: str = "kavithadee/infrapilot-ai"  # GITHUB_TARGET_REPO
    github_base_branch: str = "main"     # GITHUB_BASE_BRANCH

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse cors_origins into a list. Handles JSON array, comma-separated, or single URL."""
        v = self.cors_origins.strip()
        if not v:
            return _DEFAULT_CORS.split(",")
        if v.startswith("["):
            try:
                parsed = json.loads(v)
                return [str(o).strip() for o in parsed if o]
            except json.JSONDecodeError:
                pass
        return [o.strip() for o in v.split(",") if o.strip()]


# Single shared instance — import this everywhere
settings = Settings()
