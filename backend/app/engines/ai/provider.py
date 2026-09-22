"""The AI provider abstraction.

The rest of the platform talks to :class:`AIProvider` and never to a vendor
SDK. A provider has exactly one job: send a system prompt and a user prompt
to a model and hand back the text it produced. It does not load
assessments, read MongoDB, build prompts, validate output or persist
anything - that is :class:`~app.services.ai_analysis_service.AIAnalysisService`.

Every failure a provider can hit is raised as :class:`AIProviderError` with a
fixed category and a message written by the platform, so no provider text
(which could echo credentials or headers) ever reaches logs, MongoDB or an
HTTP response.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class ProviderErrorCategory(str, Enum):
    CONFIGURATION = "configuration"
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    NETWORK = "network"
    INVALID_MODEL = "invalid_model"
    BAD_REQUEST = "bad_request"
    PROVIDER_ERROR = "provider_error"
    INVALID_RESPONSE = "invalid_response"


class AIProviderError(Exception):
    """A provider could not produce a usable response. Safe to show."""

    def __init__(
        self,
        category: ProviderErrorCategory,
        message: str,
        *,
        status_code: int | None = None,
        provider_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.message = message
        self.status_code = status_code
        #: The provider's machine-readable code (e.g. ``invalid_api_key``).
        self.provider_code = provider_code


@dataclass
class ProviderResult:
    """The raw text a model returned, plus safe metadata about the call."""

    text: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str | None = None


class AIProvider(ABC):
    """Sends prompts to a model. Knows nothing about assessments."""

    #: Short identifier stored on every analysis, e.g. ``"openai"``.
    name: str = "provider"

    @property
    @abstractmethod
    def model(self) -> str:
        """The configured model identifier (may be empty if unconfigured)."""

    @abstractmethod
    async def analyze(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        """Return the model's reply to the two prompts.

        The system prompt carries instructions; the user prompt carries the
        delimited, untrusted assessment data. Implementations must keep them
        in separate messages and must raise :class:`AIProviderError` for
        every failure.
        """


class UnconfiguredProvider(AIProvider):
    """Stands in when ``AI_PROVIDER`` names nothing this platform supports.

    Analysis then fails with a clear configuration error, recorded like any
    other failure, instead of the API refusing to start.
    """

    def __init__(self, name: str, reason: str) -> None:
        self.name = name or "unconfigured"
        self._reason = reason

    @property
    def model(self) -> str:
        return ""

    async def analyze(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        raise AIProviderError(ProviderErrorCategory.CONFIGURATION, self._reason)
