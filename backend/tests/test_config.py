"""Settings tests, including guard rails against the retired stack."""

from __future__ import annotations

from app.core.config import BACKEND_ROOT, ENV_FILE, PROJECT_ROOT, Settings


def test_the_production_database_name_is_unchanged() -> None:
    """``ai_qa_security`` is the shipped default and must stay that way.

    Read from the model's own default rather than from the loaded settings,
    so that a suite pointed at a scratch database (``MONGODB_DATABASE=...``)
    still proves the production default is intact instead of asserting
    whatever this particular run happens to be using.
    """
    assert Settings.model_fields["mongodb_database"].default == "ai_qa_security"


def test_defaults_target_the_native_local_stack(settings: Settings) -> None:
    assert settings.mongodb_uri.startswith("mongodb://")
    assert settings.mongodb_database, "a database name must always be configured"
    assert settings.backend_host == "127.0.0.1"
    assert settings.backend_port == 8000
    assert "5173" in settings.frontend_url


def test_env_file_resolves_absolutely_under_backend() -> None:
    """uvicorn must load the same .env from any working directory."""
    assert ENV_FILE.is_absolute()
    assert ENV_FILE.parent == BACKEND_ROOT
    assert BACKEND_ROOT.name == "backend"
    assert PROJECT_ROOT == BACKEND_ROOT.parent


def test_no_container_or_postgres_artefacts_in_config(settings: Settings) -> None:
    """The stack is native processes + MongoDB. Nothing else may creep back."""
    blob = " ".join(
        [
            settings.mongodb_uri,
            settings.frontend_url,
            f"{settings.zap_host}:{settings.zap_port}",
            str(settings.qa_workspace_root),
        ]
    ).lower()
    for banned in ("host.docker.internal", "postgres", "psycopg", ":5432"):
        assert banned not in blob, f"{banned!r} must not appear in configuration"


def test_cors_allow_list_covers_both_loopback_spellings(settings: Settings) -> None:
    origins = settings.cors_origins
    assert "http://localhost:5173" in origins
    assert "http://127.0.0.1:5173" in origins
    assert "*" not in origins, "a security tool should not run an open CORS policy"
    assert len(origins) == len(set(origins))


def test_blank_workspace_env_var_falls_back_to_the_default() -> None:
    """`QA_WORKSPACE_ROOT=` in .env must not resolve to the CWD."""
    configured = Settings(qa_workspace_root="", reports_root="")
    assert configured.qa_workspace_root == BACKEND_ROOT / ".qa-workspace"
    assert configured.reports_root == PROJECT_ROOT / "reports"


def test_log_level_is_normalised() -> None:
    assert Settings(log_level="debug").log_level == "DEBUG"
