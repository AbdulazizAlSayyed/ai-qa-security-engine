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

    # --- AI analysis (Phase 5) --------------------------------------------
    #: Which AIProvider implementation analyses evidence: "openai" or "gemini".
    ai_provider: str = "openai"
    #: Read from the environment / backend/.env only. Never commit it.
    openai_api_key: str = ""
    #: Deliberately no default: the model is a configuration decision, and a
    #: guessed name would fail in a confusing way. Analysis reports a clear
    #: configuration error until this is set.
    openai_model: str = ""
    openai_timeout_seconds: float = 90.0
    #: Retries inside the SDK for transient errors (429 / 5xx / network).
    openai_max_retries: int = 1
    #: Google Gemini, an alternative provider behind the same AIProvider
    #: abstraction (used when AI_PROVIDER=gemini). Same "read from .env only,
    #: never commit it" rule as the OpenAI key.
    gemini_api_key: str = ""
    #: Deliberately no default, for the same reason as openai_model.
    gemini_model: str = ""
    gemini_timeout_seconds: float = 90.0
    #: Output budget. Reasoning models spend part of it thinking, so it is
    #: generous; a truncated answer is rejected, never half-parsed.
    ai_max_output_tokens: int = 8000
    #: Context budget for the evidence handed to the model. Anything left out
    #: is recorded on the analysis, never dropped silently.
    ai_max_evidence_items: int = 300
    ai_max_context_chars: int = 60_000
    #: An analysis still "running" after this long is treated as abandoned
    #: (e.g. the server stopped mid-call), so the assessment is not locked.
    ai_analysis_stale_seconds: int = 600

    # --- Correlation & prioritization (Phase 6) ---------------------------
    #: A correlation run still "running" after this long is treated as
    #: abandoned, so a crashed run never blocks re-processing.
    correlation_stale_seconds: int = 300

    # --- Recommendations (Phase 8, advisory only) ------------------------
    #: Most important issues supplied to one generation; the rest are listed
    #: as omitted on the generation summary. A generation still running after
    #: AI_ANALYSIS_STALE_SECONDS is treated as abandoned.
    recommendation_max_issues: int = 50

    # --- Retest (Phase 9) -------------------------------------------------
    #: A retest still "running" after this long is recorded as abandoned,
    #: which releases the per-recommendation lock. Longer than a ZAP scan.
    retest_stale_seconds: int = 1800

    # --- Reports (Phase 10) ------------------------------------------------
    #: A report still "running" after this long is recorded as abandoned.
    #: Rendered HTML / PDF files are written under ``reports_root``.
    report_stale_seconds: int = 600

    # --- QA engine (Playwright) ------------------------------------------
    qa_headless: bool = True
    #: Blank uses Playwright's bundled Chromium. "chrome" or "msedge" drive a
    #: locally installed browser instead.
    qa_browser_channel: str = ""
    #: Kept short so a dead target fails fast instead of holding a request.
    qa_navigation_timeout_ms: int = 15_000
    qa_test_timeout_ms: int = 30_000

    # --- Security engine -------------------------------------------------
    security_enabled: bool = True
    #: Whole-scan budget handed to each external scanner.
    security_timeout_seconds: int = 180

    # OWASP ZAP runs as its own native process and is reached over its REST
    # API. Port 8090 rather than ZAP's 8080 default, which is very commonly
    # already taken on a developer machine.
    zap_enabled: bool = True
    zap_host: str = "127.0.0.1"
    zap_port: int = 8090
    zap_api_key: str = ""
    #: Absolute path to zap.bat / zap.sh, when the platform starts ZAP itself.
    #: Left blank means "ZAP is already running"; never hardcode a machine path.
    zap_executable: str = ""
    zap_spider: bool = True
    zap_spider_max_children: int = 10

    # Custom API probes. Safe methods only; see engines/security/api_probes.py.
    api_probes_enabled: bool = True
    api_probe_timeout_seconds: int = 10
    #: Local targets routinely use self-signed certificates.
    api_probe_verify_tls: bool = False

    # Semgrep is optional; a scan succeeds whether or not it is installed.
    semgrep_enabled: bool = True
    semgrep_executable: str = "semgrep"
    semgrep_ruleset: str = "p/security-audit"

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
