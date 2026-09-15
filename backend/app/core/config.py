"""Application settings.

Every tunable value the backend needs is declared here and loaded from
``backend/.env``. The .env path is resolved absolutely from this file's own
location, so uvicorn resolves identical settings no matter which working
directory it was started from.

Stack note: this project runs as native local processes against MongoDB.
There is no Docker, no PostgreSQL and no container networking, so service
hosts are plain ``localhost`` / ``127.0.0.1``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# .../ai-qa-security-engine/backend/app/core/config.py -> .../backend
BACKEND_ROOT: Path = Path(__file__).resolve().parents[2]
PROJECT_ROOT: Path = BACKEND_ROOT.parent
ENV_FILE: Path = BACKEND_ROOT / ".env"


class Settings(BaseSettings):
    """Runtime configuration, populated from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Service identity ------------------------------------------------
    project_name: str = "AI QA Engineer + AI Cybersecurity QA Engineer"
    api_version: str = "0.1.0"
    environment: str = "development"

    # --- MongoDB ---------------------------------------------------------
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_database: str = "ai_qa_security"
    # Keep server selection short so /health fails fast instead of hanging
    # for PyMongo's 30s default when MongoDB is down.
    mongodb_timeout_ms: int = 3000

    # --- HTTP server -----------------------------------------------------
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    frontend_url: str = "http://localhost:5173"

    # --- AI provider (wired up in Phase 5) -------------------------------
    ai_provider: str = "openai"
    openai_api_key: str = ""
    openai_model: str = ""

    # --- Security tooling (wired up in Phase 3) --------------------------
    zap_api_url: str = "http://127.0.0.1:8080"
    zap_api_key: str = ""

    # --- Filesystem workspaces -------------------------------------------
    qa_workspace_root: Path = BACKEND_ROOT / ".qa-workspace"
    reports_root: Path = PROJECT_ROOT / "reports"

    # --- Logging ---------------------------------------------------------
    log_level: str = "INFO"

    @field_validator("qa_workspace_root", "reports_root", mode="before")
    @classmethod
    def _blank_path_falls_back_to_default(cls, value: object, info) -> object:
        """Treat ``QA_WORKSPACE_ROOT=`` in .env as "use the default".

        Without this, an empty env var would resolve to ``Path(".")`` and the
        QA engine would scatter workspaces into whatever directory uvicorn
        happened to start in.
        """
        if value is None or (isinstance(value, str) and not value.strip()):
            defaults = {
                "qa_workspace_root": BACKEND_ROOT / ".qa-workspace",
                "reports_root": PROJECT_ROOT / "reports",
            }
            return defaults[info.field_name]
        return value

    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, value: str) -> str:
        return value.strip().upper() or "INFO"

    @property
    def cors_origins(self) -> list[str]:
        """Explicit allow-list for the Vite dev server.

        Both spellings of loopback are included because the browser sends
        whichever one the user typed in the address bar. A wildcard is
        deliberately not used: this platform drives security testing tools,
        so its own surface stays tight.
        """
        origins: list[str] = [self.frontend_url]
        if "localhost" in self.frontend_url:
            origins.append(self.frontend_url.replace("localhost", "127.0.0.1"))
        elif "127.0.0.1" in self.frontend_url:
            origins.append(self.frontend_url.replace("127.0.0.1", "localhost"))
        # dict.fromkeys preserves order while removing duplicates
        return list(dict.fromkeys(origins))

    @property
    def is_development(self) -> bool:
        return self.environment.lower() == "development"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
