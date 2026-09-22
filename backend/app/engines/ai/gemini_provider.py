"""Google Gemini implementation of :class:`AIProvider`.

The only module in the platform that imports the Gemini SDK. It sends the
system prompt as ``system_instruction`` and the user prompt as the message
content, asks for a JSON response, and returns the text. It never touches
MongoDB, assessments or evidence, and it never sees anything but the prompts
it is handed.

Every SDK exception is translated into :class:`AIProviderError` with a
message written here. Provider error text is deliberately *not* passed
through: it can quote parts of the key or request, and it ends up in the
database and the UI.
"""

from __future__ import annotations

from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from app.engines.ai.provider import (
    AIProvider,
    AIProviderError,
    ProviderErrorCategory,
    ProviderResult,
)

_TRUNCATED = {"MAX_TOKENS", "FinishReason.MAX_TOKENS", "2"}
_FILTERED = {
    "SAFETY",
    "RECITATION",
    "FinishReason.SAFETY",
    "FinishReason.RECITATION",
    "PROHIBITED_CONTENT",
    "FinishReason.PROHIBITED_CONTENT",
}


def _looks_like_key_error(message: str | None) -> bool:
    lowered = (message or "").lower()
    return "api key" in lowered or "api_key" in lowered


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 90.0,
        max_output_tokens: int = 8000,
        client: Any | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._model = (model or "").strip()
        self._timeout = timeout_seconds
        self._max_output_tokens = max_output_tokens
        #: Injected in tests; created lazily otherwise, so a missing key is
        #: reported as a configuration error at analysis time, not a crash.
        self._client = client

    @property
    def model(self) -> str:
        return self._model

    def __repr__(self) -> str:  # never show the key
        return f"GeminiProvider(model={self._model!r}, key_configured={bool(self._api_key)})"

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = genai.Client(
                api_key=self._api_key,
                http_options=genai_types.HttpOptions(timeout=int(self._timeout * 1000)),
            )
        return self._client

    async def analyze(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        if not self._api_key:
            raise AIProviderError(
                ProviderErrorCategory.CONFIGURATION,
                "GEMINI_API_KEY is not configured. Set it in backend/.env or the "
                "environment, then restart the backend.",
            )
        if not self._model:
            raise AIProviderError(
                ProviderErrorCategory.CONFIGURATION,
                "GEMINI_MODEL is not configured. Set it to a Gemini model your key can "
                "use in backend/.env, then restart the backend.",
            )

        try:
            response = await self._get_client().aio.models.generate_content(
                model=self._model,
                contents=user_prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    max_output_tokens=self._max_output_tokens,
                ),
            )
        except genai_errors.ClientError as exc:
            raise self._client_error(exc) from exc
        except genai_errors.ServerError as exc:
            raise self._server_error(exc) from exc
        except genai_errors.APIError as exc:
            raise AIProviderError(
                ProviderErrorCategory.PROVIDER_ERROR,
                f"The AI provider returned an error (HTTP {getattr(exc, 'code', 'unknown')}).",
                status_code=getattr(exc, "code", None),
                provider_code=_str_or_none(getattr(exc, "status", None)),
            ) from exc
        except Exception as exc:
            # Connection/timeout failures happen before any HTTP response
            # exists, so the SDK's own response-based error types (above)
            # never see them; they surface as whatever the transport underneath
            # raises. Classified by class name only, so this module never has
            # to import a transport library itself.
            raise self._transport_error(exc) from exc

        return self._read(response)

    def _client_error(self, exc: Exception) -> AIProviderError:
        code = getattr(exc, "code", None)
        status = _str_or_none(getattr(exc, "status", None))
        message = getattr(exc, "message", None) or str(exc)
        if code == 400 and _looks_like_key_error(message):
            return AIProviderError(
                ProviderErrorCategory.AUTHENTICATION,
                "The AI provider rejected the API key (HTTP 400). Check GEMINI_API_KEY.",
                status_code=400,
                provider_code=status,
            )
        if code == 403:
            return AIProviderError(
                ProviderErrorCategory.PERMISSION,
                "The API key is not allowed to use this model or endpoint (HTTP 403).",
                status_code=403,
                provider_code=status,
            )
        if code == 404:
            return AIProviderError(
                ProviderErrorCategory.INVALID_MODEL,
                f"The model {self._model!r} does not exist or is not available to this "
                "key (HTTP 404). Check GEMINI_MODEL.",
                status_code=404,
                provider_code=status,
            )
        if code == 429:
            return AIProviderError(
                ProviderErrorCategory.RATE_LIMIT,
                "The AI provider rate limit or quota was exceeded (HTTP 429). Try again later.",
                status_code=429,
                provider_code=status,
            )
        return AIProviderError(
            ProviderErrorCategory.BAD_REQUEST,
            f"The AI provider rejected the request (HTTP {code}{f', {status}' if status else ''}).",
            status_code=code,
            provider_code=status,
        )

    def _server_error(self, exc: Exception) -> AIProviderError:
        code = getattr(exc, "code", None)
        status = _str_or_none(getattr(exc, "status", None))
        if code == 504:
            return AIProviderError(
                ProviderErrorCategory.TIMEOUT,
                f"The AI provider did not answer within {self._timeout:g} seconds.",
                status_code=504,
                provider_code=status,
            )
        return AIProviderError(
            ProviderErrorCategory.PROVIDER_ERROR,
            f"The AI provider returned an error (HTTP {code}).",
            status_code=code,
            provider_code=status,
        )

    def _transport_error(self, exc: Exception) -> AIProviderError:
        kind = type(exc).__name__
        if "Timeout" in kind:
            return AIProviderError(
                ProviderErrorCategory.TIMEOUT,
                f"The AI provider did not answer within {self._timeout:g} seconds.",
            )
        return AIProviderError(
            ProviderErrorCategory.NETWORK,
            "Could not reach the AI provider (network or DNS failure).",
        )

    def _read(self, response: Any) -> ProviderResult:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            feedback = getattr(response, "prompt_feedback", None)
            block_reason = getattr(feedback, "block_reason", None) if feedback else None
            if block_reason:
                raise AIProviderError(
                    ProviderErrorCategory.INVALID_RESPONSE,
                    "The provider's content filter stopped the answer.",
                )
            raise AIProviderError(
                ProviderErrorCategory.INVALID_RESPONSE, "The AI provider returned no choices."
            )

        candidate = candidates[0]
        finish_reason_obj = getattr(candidate, "finish_reason", None)
        finish_reason = str(finish_reason_obj) if finish_reason_obj is not None else None

        if finish_reason in _TRUNCATED:
            raise AIProviderError(
                ProviderErrorCategory.INVALID_RESPONSE,
                "The model's answer was cut off by the output token limit, so it cannot be "
                "trusted. Raise AI_MAX_OUTPUT_TOKENS.",
            )
        if finish_reason in _FILTERED:
            raise AIProviderError(
                ProviderErrorCategory.INVALID_RESPONSE,
                "The provider's content filter stopped the answer.",
            )

        try:
            text = response.text
        except Exception:  # the SDK's .text property can itself raise
            text = None
        if not isinstance(text, str) or not text.strip():
            raise AIProviderError(
                ProviderErrorCategory.INVALID_RESPONSE, "The AI provider returned an empty answer."
            )

        usage_obj = getattr(response, "usage_metadata", None)
        usage: dict[str, int] = {}
        for target, sources in (
            ("input_tokens", ("prompt_token_count", "input_tokens")),
            ("output_tokens", ("candidates_token_count", "output_tokens")),
            ("total_tokens", ("total_token_count", "total_tokens")),
        ):
            for source in sources:
                value = getattr(usage_obj, source, None) if usage_obj is not None else None
                if isinstance(value, int):
                    usage[target] = value
                    break

        return ProviderResult(
            text=text,
            model=self._model,
            usage=usage,
            finish_reason=finish_reason,
        )


def _str_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None
