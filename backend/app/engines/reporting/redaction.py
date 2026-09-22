"""Secret handling for reports.

Redaction reuses Phase 5's ``sanitize_text`` - one redaction implementation
for the whole platform. On top of that, the rendered report is audited by
:func:`find_leaks` before anything is persisted: a *detector* (not a second
redactor) for credentials that must never appear in a report, including the
literal secret values configured in this process (OpenAI / ZAP keys, a
MongoDB URI with credentials). A report with a hit is not stored.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from app.engines.ai.context import sanitize_text

#: Everything already masked by sanitize_text reads "[REDACTED]".
_NOT_REDACTED = r"(?!\[REDACTED\])"

LEAK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{4,}")),
    ("bearer_token", re.compile(rf"(?i)\b(?:bearer|basic)\s+{_NOT_REDACTED}[A-Za-z0-9\-._~+/]{{8,}}")),
    ("authorization_header", re.compile(rf"(?i)\b(?:proxy-)?authorization\s*[:=]\s*{_NOT_REDACTED}[^\s\"'<,;]{{4,}}")),
    ("cookie_header", re.compile(rf"(?i)\b(?:set-cookie|cookie)\s*[:=]\s*{_NOT_REDACTED}[^\s\"'<;]{{4,}}=")),
    (
        "secret_assignment",
        re.compile(
            rf"(?i)[\"']?\b(?:password|passwd|pwd|client[_-]?secret|api[_-]?key|apikey|access[_-]?token|"
            rf"refresh[_-]?token|auth[_-]?token|session[_-]?id)\b[\"']?\s*[:=]\s*[\"']?{_NOT_REDACTED}[^\"'\s,&;}}<]{{3,}}"
        ),
    ),
    ("url_credentials", re.compile(rf"(?i)\b[a-z][a-z0-9+.\-]*://{_NOT_REDACTED}[^\s/@:<\"']+:[^\s/@<\"']+@")),
]


def clean(value: Any, limit: int = 2000) -> str | None:
    """Text for a report: redacted with the Phase 5 filter, then capped."""
    if value is None:
        return None
    text, _ = sanitize_text(str(value))
    if len(text) > limit:
        text = text[:limit] + " [truncated]"
    return text


def clean_list(values: Iterable[Any] | None, limit: int = 2000) -> list[str]:
    return [clean(v, limit) or "" for v in values or []]


def known_secrets(settings: Any) -> list[str]:
    """Configured secret values that must never appear in a report."""
    values = [getattr(settings, "openai_api_key", ""), getattr(settings, "zap_api_key", "")]
    uri = str(getattr(settings, "mongodb_uri", "") or "")
    match = re.search(r"://([^/@]+)@", uri)
    if match:
        values.append(match.group(1))
    return [v for v in values if v and len(v) >= 6]


def find_leaks(text: str, secrets: Iterable[str] = ()) -> list[str]:
    """Names of leak kinds found in ``text`` - never the matched values."""
    found = [name for name, pattern in LEAK_PATTERNS if pattern.search(text)]
    if any(secret in text for secret in secrets):
        found.append("configured_secret")
    return found
