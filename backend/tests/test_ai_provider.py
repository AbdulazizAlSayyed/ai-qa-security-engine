"""OpenAIProvider tests against a mocked SDK client. No network, no key."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest

from app.engines.ai.openai_provider import OpenAIProvider
from app.engines.ai.provider import (
    AIProvider,
    AIProviderError,
    ProviderErrorCategory,
    UnconfiguredProvider,
)

FAKE_KEY = "sk-test-DO-NOT-LEAK-0123456789abcdef"
REQUEST = httpx.Request("POST", "https://api.openai.invalid/v1/chat/completions")


def response(
    content: str | None = '{"ok": true}',
    *,
    finish_reason: str = "stop",
    refusal: str | None = None,
    choices: bool = True,
) -> Any:
    message = SimpleNamespace(content=content, refusal=refusal)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)] if choices else [],
        model="served-model-2026",
        usage=SimpleNamespace(prompt_tokens=120, completion_tokens=40, total_tokens=160),
    )


class FakeClient:
    """Stands in for openai.AsyncOpenAI: records calls, returns or raises."""

    def __init__(self, result: Any = None, exc: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._result = result if result is not None else response()
        self._exc = exc
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._exc is not None:
            raise self._exc
        return self._result


def provider(client: FakeClient, *, api_key: str = FAKE_KEY, model: str = "configured-model") -> OpenAIProvider:
    return OpenAIProvider(
        api_key=api_key, model=model, timeout_seconds=12, max_output_tokens=900, client=client
    )


def status_error(cls: type, status: int, code: str | None = None, message: str = "boom") -> Exception:
    body = {"message": message, "code": code} if code else {"message": message}
    return cls(message, response=httpx.Response(status, request=REQUEST), body=body)


# --- the happy path ----------------------------------------------------------


async def test_success_sends_separate_messages_as_json_and_returns_text() -> None:
    client = FakeClient()
    result = await provider(client).analyze(system_prompt="SYS", user_prompt="DATA")

    assert result.text == '{"ok": true}'
    assert result.model == "served-model-2026"
    assert result.usage == {"input_tokens": 120, "output_tokens": 40, "total_tokens": 160}

    (call,) = client.calls
    assert call["model"] == "configured-model"
    assert call["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "DATA"},
    ]
    assert call["response_format"] == {"type": "json_object"}
    assert call["max_completion_tokens"] == 900
    # Sampling knobs some models reject are never sent.
    assert "temperature" not in call


def test_openai_provider_is_an_ai_provider_and_hides_its_key() -> None:
    p = provider(FakeClient())
    assert isinstance(p, AIProvider)
    assert p.name == "openai"
    assert p.model == "configured-model"
    assert FAKE_KEY not in repr(p)


# --- configuration -----------------------------------------------------------


async def test_missing_key_is_a_configuration_error_and_nothing_is_sent() -> None:
    client = FakeClient()
    with pytest.raises(AIProviderError) as info:
        await provider(client, api_key="  ").analyze(system_prompt="s", user_prompt="u")
    assert info.value.category is ProviderErrorCategory.CONFIGURATION
    assert "OPENAI_API_KEY" in info.value.message
    assert client.calls == []


async def test_missing_model_is_a_configuration_error() -> None:
    client = FakeClient()
    with pytest.raises(AIProviderError) as info:
        await provider(client, model="").analyze(system_prompt="s", user_prompt="u")
    assert info.value.category is ProviderErrorCategory.CONFIGURATION
    assert "OPENAI_MODEL" in info.value.message
    assert client.calls == []


# --- provider failures -------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "category", "status"),
    [
        (openai.APITimeoutError(request=REQUEST), ProviderErrorCategory.TIMEOUT, None),
        (openai.APIConnectionError(request=REQUEST), ProviderErrorCategory.NETWORK, None),
        (status_error(openai.AuthenticationError, 401, "invalid_api_key"),
         ProviderErrorCategory.AUTHENTICATION, 401),
        (status_error(openai.PermissionDeniedError, 403), ProviderErrorCategory.PERMISSION, 403),
        (status_error(openai.RateLimitError, 429, "rate_limit_exceeded"),
         ProviderErrorCategory.RATE_LIMIT, 429),
        (status_error(openai.NotFoundError, 404, "model_not_found"),
         ProviderErrorCategory.INVALID_MODEL, 404),
        (status_error(openai.BadRequestError, 400, "model_not_found"),
         ProviderErrorCategory.INVALID_MODEL, 400),
        (status_error(openai.BadRequestError, 400, "context_length_exceeded"),
         ProviderErrorCategory.BAD_REQUEST, 400),
        (status_error(openai.InternalServerError, 500), ProviderErrorCategory.PROVIDER_ERROR, 500),
    ],
)
async def test_sdk_errors_become_safe_categorised_errors(
    exc: Exception, category: ProviderErrorCategory, status: int | None
) -> None:
    with pytest.raises(AIProviderError) as info:
        await provider(FakeClient(exc=exc)).analyze(system_prompt="s", user_prompt="u")
    assert info.value.category is category
    assert info.value.status_code == status


async def test_provider_text_is_never_passed_through() -> None:
    """Provider messages can quote the key; ours never do."""
    leaky = status_error(
        openai.AuthenticationError, 401, "invalid_api_key",
        message=f"Incorrect API key provided: {FAKE_KEY}. Authorization: Bearer {FAKE_KEY}",
    )
    with pytest.raises(AIProviderError) as info:
        await provider(FakeClient(exc=leaky)).analyze(system_prompt="s", user_prompt="u")
    assert FAKE_KEY not in info.value.message
    assert FAKE_KEY not in str(info.value)
    assert info.value.provider_code == "invalid_api_key"


# --- unusable answers --------------------------------------------------------


@pytest.mark.parametrize(
    "reply",
    [
        response(choices=False),
        response(content=None),
        response(content="   "),
        response(refusal="I can't help with that."),
        response(content='{"partial": ', finish_reason="length"),
        response(finish_reason="content_filter"),
    ],
)
async def test_unusable_answers_are_invalid_response(reply: Any) -> None:
    with pytest.raises(AIProviderError) as info:
        await provider(FakeClient(result=reply)).analyze(system_prompt="s", user_prompt="u")
    assert info.value.category is ProviderErrorCategory.INVALID_RESPONSE


# --- provider selection ------------------------------------------------------


def test_dependency_builds_the_openai_provider_from_configuration() -> None:
    from app.api.dependencies import get_ai_provider
    from app.core.config import Settings

    chosen = get_ai_provider(Settings(ai_provider="OpenAI", openai_api_key=FAKE_KEY, openai_model="m-1"))
    assert isinstance(chosen, OpenAIProvider)
    assert chosen.model == "m-1"


async def test_unknown_provider_fails_as_configuration_not_at_startup() -> None:
    from app.api.dependencies import get_ai_provider
    from app.core.config import Settings

    chosen = get_ai_provider(Settings(ai_provider="someone-else"))
    assert isinstance(chosen, UnconfiguredProvider)
    with pytest.raises(AIProviderError) as info:
        await chosen.analyze(system_prompt="s", user_prompt="u")
    assert info.value.category is ProviderErrorCategory.CONFIGURATION
