"""GeminiProvider tests against a mocked SDK client. No network, no key."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import errors as genai_errors

from app.engines.ai.gemini_provider import GeminiProvider
from app.engines.ai.provider import (
    AIProvider,
    AIProviderError,
    ProviderErrorCategory,
    UnconfiguredProvider,
)

FAKE_KEY = "AIzaSy-test-DO-NOT-LEAK-0123456789abcdef"


def response(
    text: str | None = '{"ok": true}',
    *,
    finish_reason: str = "STOP",
    candidates: bool = True,
    block_reason: str | None = None,
) -> Any:
    candidate = SimpleNamespace(finish_reason=finish_reason)
    return SimpleNamespace(
        candidates=[candidate] if candidates else [],
        text=text,
        prompt_feedback=SimpleNamespace(block_reason=block_reason),
        usage_metadata=SimpleNamespace(
            prompt_token_count=120, candidates_token_count=40, total_token_count=160
        ),
    )


class _RaisingText:
    """A response whose .text property itself raises, like the real SDK can."""

    candidates = [SimpleNamespace(finish_reason="STOP")]
    prompt_feedback = SimpleNamespace(block_reason=None)
    usage_metadata = None

    @property
    def text(self) -> str:
        raise ValueError("no text part")


class FakeModels:
    def __init__(self, result: Any = None, exc: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._result = result if result is not None else response()
        self._exc = exc

    async def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._exc is not None:
            raise self._exc
        return self._result


class FakeClient:
    """Stands in for genai.Client: records calls, returns or raises."""

    def __init__(self, result: Any = None, exc: Exception | None = None) -> None:
        self._models = FakeModels(result=result, exc=exc)
        self.aio = SimpleNamespace(models=self._models)

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self._models.calls


def provider(client: FakeClient, *, api_key: str = FAKE_KEY, model: str = "gemini-2.5-flash-lite") -> GeminiProvider:
    return GeminiProvider(
        api_key=api_key, model=model, timeout_seconds=12, max_output_tokens=900, client=client
    )


def client_error(status_code: int, status: str | None = None, message: str = "boom") -> genai_errors.ClientError:
    body = {"error": {"code": status_code, "message": message, "status": status}}
    return genai_errors.ClientError(status_code, body)


def server_error(status_code: int, status: str | None = None, message: str = "boom") -> genai_errors.ServerError:
    body = {"error": {"code": status_code, "message": message, "status": status}}
    return genai_errors.ServerError(status_code, body)


# --- the happy path ----------------------------------------------------------


async def test_success_sends_system_instruction_and_json_config_and_returns_text() -> None:
    client = FakeClient()
    result = await provider(client).analyze(system_prompt="SYS", user_prompt="DATA")

    assert result.text == '{"ok": true}'
    assert result.model == "gemini-2.5-flash-lite"
    assert result.usage == {"input_tokens": 120, "output_tokens": 40, "total_tokens": 160}

    (call,) = client.calls
    assert call["model"] == "gemini-2.5-flash-lite"
    assert call["contents"] == "DATA"
    assert call["config"].system_instruction == "SYS"
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].max_output_tokens == 900


def test_gemini_provider_is_an_ai_provider_and_hides_its_key() -> None:
    p = provider(FakeClient())
    assert isinstance(p, AIProvider)
    assert p.name == "gemini"
    assert p.model == "gemini-2.5-flash-lite"
    assert FAKE_KEY not in repr(p)


# --- configuration -----------------------------------------------------------


async def test_missing_key_is_a_configuration_error_and_nothing_is_sent() -> None:
    client = FakeClient()
    with pytest.raises(AIProviderError) as info:
        await provider(client, api_key="  ").analyze(system_prompt="s", user_prompt="u")
    assert info.value.category is ProviderErrorCategory.CONFIGURATION
    assert "GEMINI_API_KEY" in info.value.message
    assert client.calls == []


async def test_missing_model_is_a_configuration_error() -> None:
    client = FakeClient()
    with pytest.raises(AIProviderError) as info:
        await provider(client, model="").analyze(system_prompt="s", user_prompt="u")
    assert info.value.category is ProviderErrorCategory.CONFIGURATION
    assert "GEMINI_MODEL" in info.value.message
    assert client.calls == []


# --- provider failures -------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "category", "status"),
    [
        (client_error(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key."),
         ProviderErrorCategory.AUTHENTICATION, 400),
        (client_error(400, "INVALID_ARGUMENT", "The request body is malformed."),
         ProviderErrorCategory.BAD_REQUEST, 400),
        (client_error(403, "PERMISSION_DENIED"), ProviderErrorCategory.PERMISSION, 403),
        (client_error(404, "NOT_FOUND"), ProviderErrorCategory.INVALID_MODEL, 404),
        (client_error(429, "RESOURCE_EXHAUSTED"), ProviderErrorCategory.RATE_LIMIT, 429),
        (server_error(500, "INTERNAL"), ProviderErrorCategory.PROVIDER_ERROR, 500),
        (server_error(503, "UNAVAILABLE"), ProviderErrorCategory.PROVIDER_ERROR, 503),
        (server_error(504, "DEADLINE_EXCEEDED"), ProviderErrorCategory.TIMEOUT, 504),
    ],
)
async def test_sdk_errors_become_safe_categorised_errors(
    exc: Exception, category: ProviderErrorCategory, status: int
) -> None:
    with pytest.raises(AIProviderError) as info:
        await provider(FakeClient(exc=exc)).analyze(system_prompt="s", user_prompt="u")
    assert info.value.category is category
    assert info.value.status_code == status


async def test_provider_text_is_never_passed_through() -> None:
    """Provider messages can quote the key; ours never do."""
    leaky = client_error(400, "INVALID_ARGUMENT", f"API key not valid: {FAKE_KEY}")
    with pytest.raises(AIProviderError) as info:
        await provider(FakeClient(exc=leaky)).analyze(system_prompt="s", user_prompt="u")
    assert FAKE_KEY not in info.value.message
    assert FAKE_KEY not in str(info.value)


@pytest.mark.parametrize(
    ("exc", "category"),
    [
        (TimeoutError("deadline exceeded"), ProviderErrorCategory.TIMEOUT),
        (ConnectionError("dns failure"), ProviderErrorCategory.NETWORK),
        (OSError("network unreachable"), ProviderErrorCategory.NETWORK),
    ],
)
async def test_transport_failures_before_any_response_are_categorised_without_a_status_code(
    exc: Exception, category: ProviderErrorCategory
) -> None:
    with pytest.raises(AIProviderError) as info:
        await provider(FakeClient(exc=exc)).analyze(system_prompt="s", user_prompt="u")
    assert info.value.category is category
    assert info.value.status_code is None


# --- unusable answers --------------------------------------------------------


@pytest.mark.parametrize(
    "reply",
    [
        response(candidates=False),
        response(candidates=False, block_reason="SAFETY"),
        response(text=None),
        response(text="   "),
        response(finish_reason="MAX_TOKENS"),
        response(finish_reason="SAFETY"),
        response(finish_reason="RECITATION"),
        _RaisingText(),
    ],
)
async def test_unusable_answers_are_invalid_response(reply: Any) -> None:
    with pytest.raises(AIProviderError) as info:
        await provider(FakeClient(result=reply)).analyze(system_prompt="s", user_prompt="u")
    assert info.value.category is ProviderErrorCategory.INVALID_RESPONSE


# --- provider selection ------------------------------------------------------


def test_dependency_builds_the_gemini_provider_from_configuration() -> None:
    from app.api.dependencies import get_ai_provider
    from app.core.config import Settings

    chosen = get_ai_provider(Settings(ai_provider="Gemini", gemini_api_key=FAKE_KEY, gemini_model="m-1"))
    assert isinstance(chosen, GeminiProvider)
    assert chosen.model == "m-1"


async def test_unknown_provider_still_names_both_supported_providers() -> None:
    from app.api.dependencies import get_ai_provider
    from app.core.config import Settings

    chosen = get_ai_provider(Settings(ai_provider="someone-else"))
    assert isinstance(chosen, UnconfiguredProvider)
    with pytest.raises(AIProviderError) as info:
        await chosen.analyze(system_prompt="s", user_prompt="u")
    assert "openai" in info.value.message
    assert "gemini" in info.value.message


# --- import isolation ---------------------------------------------------------


def test_only_the_gemini_provider_imports_the_sdk() -> None:
    from pathlib import Path

    app_root = Path(__file__).resolve().parents[1] / "app"

    def imports(path: Path) -> str:
        return "\n".join(
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith(("import ", "from "))
        )

    importers = [
        p.name
        for p in app_root.rglob("*.py")
        if "import genai" in imports(p) or "from google" in imports(p)
    ]
    assert importers == ["gemini_provider.py"]
