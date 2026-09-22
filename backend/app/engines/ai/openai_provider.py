"""OpenAI implementation of :class:`AIProvider`.

The only module in the platform that imports the OpenAI SDK. It sends the
two prompts as separate ``system`` / ``user`` messages, asks for a JSON
object, and returns the text. It never touches MongoDB, assessments or
evidence, and it never sees anything but the prompts it is handed.

Every SDK exception is translated into :class:`AIProviderError` with a
message written here. Provider error text is deliberately *not* passed
through: it can quote parts of the key or request, and it ends up in the
database and the UI.
"""

from __future__ import annotations

from typing import Any

import openai

from app.engines.ai.provider import (
    AIProvider,
    AIProviderError,
    ProviderErrorCategory,
    ProviderResult,
)


def _provider_code(exc: Exception) -> str | None:
    code = getattr(exc, "code", None)
    return str(code) if code else None


class OpenAIProvider(AIProvider):
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 90.0,
        max_retries: int = 1,
        max_output_tokens: int = 8000,
        client: Any | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._model = (model or "").strip()
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._max_output_tokens = max_output_tokens
        #: Injected in tests; created lazily otherwise, so a missing key is
        #: reported as a configuration error at analysis time, not a crash.
        self._client = client

    @property
    def model(self) -> str:
        return self._model

    def __repr__(self) -> str:  # never show the key
        return f"OpenAIProvider(model={self._model!r}, key_configured={bool(self._api_key)})"

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = openai.AsyncOpenAI(
                api_key=self._api_key,
                timeout=self._timeout,
                max_retries=self._max_retries,
            )
        return self._client

    async def analyze(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        if not self._api_key:
            raise AIProviderError(
                ProviderErrorCategory.CONFIGURATION,
                "OPENAI_API_KEY is not configured. Set it in backend/.env or the "
                "environment, then restart the backend.",
            )
        if not self._model:
            raise AIProviderError(
                ProviderErrorCategory.CONFIGURATION,
                "OPENAI_MODEL is not configured. Set it to a chat model your key can "
                "use in backend/.env, then restart the backend.",
            )

        try:
            response = await self._get_client().chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                max_completion_tokens=self._max_output_tokens,
            )
        # Order matters: timeout is a subclass of connection error, and the
        # status errors are all subclasses of APIStatusError.
        except openai.APITimeoutError as exc:
            raise AIProviderError(
                ProviderErrorCategory.TIMEOUT,
                f"The AI provider did not answer within {self._timeout:g} seconds.",
            ) from exc
        except openai.APIConnectionError as exc:
            raise AIProviderError(
                ProviderErrorCategory.NETWORK,
                "Could not reach the AI provider (network or DNS failure).",
            ) from exc
        except openai.AuthenticationError as exc:
            raise AIProviderError(
                ProviderErrorCategory.AUTHENTICATION,
                "The AI provider rejected the API key (HTTP 401). Check OPENAI_API_KEY.",
                status_code=401,
                provider_code=_provider_code(exc),
            ) from exc
        except openai.PermissionDeniedError as exc:
            raise AIProviderError(
                ProviderErrorCategory.PERMISSION,
                "The API key is not allowed to use this model or endpoint (HTTP 403).",
                status_code=403,
                provider_code=_provider_code(exc),
            ) from exc
        except openai.RateLimitError as exc:
            raise AIProviderError(
                ProviderErrorCategory.RATE_LIMIT,
                "The AI provider rate limit or quota was exceeded (HTTP 429). Try again later.",
                status_code=429,
                provider_code=_provider_code(exc),
            ) from exc
        except openai.NotFoundError as exc:
            raise AIProviderError(
                ProviderErrorCategory.INVALID_MODEL,
                f"The model {self._model!r} does not exist or is not available to this "
                "key (HTTP 404). Check OPENAI_MODEL.",
                status_code=404,
                provider_code=_provider_code(exc),
            ) from exc
        except openai.BadRequestError as exc:
            code = _provider_code(exc)
            category = (
                ProviderErrorCategory.INVALID_MODEL
                if code and "model" in code
                else ProviderErrorCategory.BAD_REQUEST
            )
            raise AIProviderError(
                category,
                f"The AI provider rejected the request (HTTP 400{f', {code}' if code else ''}).",
                status_code=400,
                provider_code=code,
            ) from exc
        except openai.APIStatusError as exc:
            raise AIProviderError(
                ProviderErrorCategory.PROVIDER_ERROR,
                f"The AI provider returned an error (HTTP {exc.status_code}).",
                status_code=exc.status_code,
                provider_code=_provider_code(exc),
            ) from exc
        except openai.OpenAIError as exc:
            raise AIProviderError(
                ProviderErrorCategory.PROVIDER_ERROR,
                f"The AI provider call failed ({type(exc).__name__}).",
            ) from exc

        return self._read(response)

    def _read(self, response: Any) -> ProviderResult:
        choices = getattr(response, "choices", None) or []
        if not choices:
            raise AIProviderError(
                ProviderErrorCategory.INVALID_RESPONSE, "The AI provider returned no choices."
            )

        choice = choices[0]
        message = getattr(choice, "message", None)
        finish_reason = getattr(choice, "finish_reason", None)

        if message is not None and getattr(message, "refusal", None):
            raise AIProviderError(
                ProviderErrorCategory.INVALID_RESPONSE, "The model refused to produce an analysis."
            )
        if finish_reason == "length":
            raise AIProviderError(
                ProviderErrorCategory.INVALID_RESPONSE,
                "The model's answer was cut off by the output token limit, so it cannot be "
                "trusted. Raise AI_MAX_OUTPUT_TOKENS.",
            )
        if finish_reason == "content_filter":
            raise AIProviderError(
                ProviderErrorCategory.INVALID_RESPONSE,
                "The provider's content filter stopped the answer.",
            )

        text = getattr(message, "content", None) if message is not None else None
        if not isinstance(text, str) or not text.strip():
            raise AIProviderError(
                ProviderErrorCategory.INVALID_RESPONSE, "The AI provider returned an empty answer."
            )

        usage_obj = getattr(response, "usage", None)
        usage: dict[str, int] = {}
        for source, target in (
            ("prompt_tokens", "input_tokens"),
            ("completion_tokens", "output_tokens"),
            ("total_tokens", "total_tokens"),
        ):
            value = getattr(usage_obj, source, None) if usage_obj is not None else None
            if isinstance(value, int):
                usage[target] = value

        return ProviderResult(
            text=text,
            model=str(getattr(response, "model", None) or self._model),
            usage=usage,
            finish_reason=finish_reason,
        )
