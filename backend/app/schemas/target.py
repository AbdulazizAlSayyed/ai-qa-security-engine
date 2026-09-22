"""Request and response schemas for the target registry."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    ValidationInfo,
    field_validator,
)

from app.models.target import TargetType

MAX_NAME_LENGTH = 120
MAX_DESCRIPTION_LENGTH = 2000
MAX_SOURCE_PATH_LENGTH = 500

# Used for validation only. The original string is what gets stored, because
# pydantic's URL type normalises "http://localhost:3000" into
# "http://localhost:3000/", and a target's URL should come back exactly as it
# was registered.
_URL_ADAPTER = TypeAdapter(AnyHttpUrl)


def _clean_optional_url(value: str | None, field_name: str) -> str | None:
    """Validate an optional URL without rewriting it. Blank becomes ``None``."""
    if value is None:
        return None

    cleaned = value.strip()
    if not cleaned:
        return None

    try:
        _URL_ADAPTER.validate_python(cleaned)
    except ValidationError as exc:
        raise ValueError(
            f"{field_name} must be a valid http(s) URL, for example http://localhost:3000"
        ) from exc

    return cleaned


def _clean_optional_text(value: str | None) -> str | None:
    """Treat an all-whitespace optional string as absent."""
    if value is None:
        return None
    return value.strip() or None


class TargetBase(BaseModel):
    """Fields a client may supply when describing a target.

    ``extra="forbid"`` is deliberate: it makes an attempt to set ``_id`` or
    ``created_at`` a clear 422 instead of being silently ignored.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=MAX_NAME_LENGTH,
        description="Human-readable name, unique per base/API URL combination.",
        examples=["Mini E-Commerce"],
    )
    base_url: str | None = Field(
        default=None,
        description="Where the application's UI is served.",
        examples=["http://localhost:3000"],
    )
    api_url: str | None = Field(
        default=None,
        description="Where the application's API is served.",
        examples=["http://localhost:4000"],
    )
    type: TargetType = Field(
        default=TargetType.WEB_APPLICATION,
        description="Which surfaces this target exposes.",
    )
    source_path: str | None = Field(
        default=None,
        max_length=MAX_SOURCE_PATH_LENGTH,
        description="Local path to the source tree, when static analysis is possible.",
    )
    description: str = Field(
        default="",
        max_length=MAX_DESCRIPTION_LENGTH,
        description="Free-text notes about the target.",
    )
    enabled: bool = Field(
        default=True,
        description="Whether assessments may run against this target.",
    )

    @field_validator("base_url", "api_url")
    @classmethod
    def _validate_urls(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _clean_optional_url(value, info.field_name or "url")

    @field_validator("source_path")
    @classmethod
    def _validate_source_path(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)


class TargetCreate(TargetBase):
    """Payload for ``POST /targets``."""


class TargetUpdate(BaseModel):
    """Payload for ``PATCH /targets/{id}``.

    Every field is optional. Only fields actually present in the request body
    are written, so omitting ``base_url`` leaves it alone while sending
    ``"base_url": null`` clears it.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_LENGTH)
    base_url: str | None = None
    api_url: str | None = None
    type: TargetType | None = None
    source_path: str | None = Field(default=None, max_length=MAX_SOURCE_PATH_LENGTH)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    enabled: bool | None = None

    @field_validator("base_url", "api_url")
    @classmethod
    def _validate_urls(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _clean_optional_url(value, info.field_name or "url")

    @field_validator("source_path")
    @classmethod
    def _validate_source_path(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)

    def changes(self) -> dict[str, Any]:
        """Only the fields the client actually sent."""
        return self.model_dump(mode="json", exclude_unset=True)


class TargetResponse(BaseModel):
    """A registered target as the API exposes it."""

    id: str = Field(description="String form of the MongoDB ObjectId.")
    name: str
    base_url: str | None
    api_url: str | None
    type: TargetType
    source_path: str | None
    description: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class TargetDeleteResponse(BaseModel):
    """Confirmation that a target was removed."""

    deleted: bool = True
    id: str
