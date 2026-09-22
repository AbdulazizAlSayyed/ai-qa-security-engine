"""Correlation keys: the stable identity two evidence records must share.

Every key is built from structured fields the normalizer already wrote
(``finding_type``, ``source``, ``category``, ``title``, ``target_component``
and the scanner's own ``rule_id`` / ``parameter`` kept in
``evidence_payload``). Normalization is limited to what is safe and easy to
explain:

* text: lowercase, trimmed, repeated whitespace collapsed;
* URLs: scheme and host lowercased, fragment dropped, trailing ``/`` dropped;
* a leading HTTP method (``GET http://...``) split off where the rule is
  about an origin rather than one request.

Nothing is stripped from a title, and nothing is matched approximately. Two
records are the same issue only when one of the rules below produces the
identical key for both.

Rules (a record gets exactly one key, tried in this order):

``same_missing_header_and_origin``
    Security evidence reporting that a specific response header is absent,
    on the same origin. This is the one explicit cross-scanner rule: ZAP's
    passive "header missing / not set" alerts and the API probe's
    ``api-probe-missing-<header>`` checks name the same header. A header is a
    property of the server's responses, so one missing header on many URLs
    of one origin is one issue.

``same_scanner_rule_and_origin``
    Security evidence from the same scanner, same scanner rule id, same
    alert title and same origin (and the same parameter, when the scanner
    names one): repeated observations of one scanner check.

``same_normalized_identity``
    Security evidence without a scanner rule id: same scanner, same title,
    same endpoint.

``same_qa_check_and_component``
    QA evidence: same check category and title on the same component
    (the same URL, the same request, or the same source location).

QA and security evidence never share a key - the finding type is part of
every key - so a QA check and a scanner alert are never merged because
their titles look alike.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping
from urllib.parse import urlsplit

#: Bump when a rule or a normalization changes, so stored groups say which
#: rule set produced them.
CORRELATION_VERSION = "1.0"


class CorrelationRule(str, Enum):
    SAME_MISSING_HEADER_AND_ORIGIN = "same_missing_header_and_origin"
    SAME_SCANNER_RULE_AND_ORIGIN = "same_scanner_rule_and_origin"
    SAME_NORMALIZED_IDENTITY = "same_normalized_identity"
    SAME_QA_CHECK_AND_COMPONENT = "same_qa_check_and_component"


#: One-line explanation of each rule, shown next to every group.
RULE_DESCRIPTIONS: dict[CorrelationRule, str] = {
    CorrelationRule.SAME_MISSING_HEADER_AND_ORIGIN: (
        "Security evidence reporting the same missing response header on the same origin."
    ),
    CorrelationRule.SAME_SCANNER_RULE_AND_ORIGIN: (
        "Repeated observations of the same scanner rule (same rule id and alert title) "
        "on the same origin."
    ),
    CorrelationRule.SAME_NORMALIZED_IDENTITY: (
        "Security evidence with the same scanner and title on the same endpoint "
        "(the scanner gave no rule id)."
    ),
    CorrelationRule.SAME_QA_CHECK_AND_COMPONENT: (
        "The same QA check (category and title) on the same component."
    ),
}

#: ZAP passive rules that report one specific absent response header. Only
#: alerts whose title says the header is missing / not set use this mapping,
#: because some of these plugin ids also raise other alert variants.
ZAP_MISSING_HEADER_RULES: dict[str, str] = {
    "10020": "x-frame-options",
    "10021": "x-content-type-options",
    "10035": "strict-transport-security",
    "10038": "content-security-policy",
    "10063": "permissions-policy",
}

API_PROBE_MISSING_PREFIX = "api-probe-missing-"
#: Short names the API probe uses in its rule ids.
API_PROBE_HEADER_ALIASES: dict[str, str] = {"hsts": "strict-transport-security"}

_MISSING_TITLE_MARKERS = ("missing", "not set")
_METHOD_PREFIX = re.compile(
    r"^(GET|HEAD|OPTIONS|POST|PUT|PATCH|DELETE|TRACE|CONNECT)\s+(.*)$", re.IGNORECASE
)
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class CorrelationKey:
    rule: CorrelationRule
    finding_type: str
    #: What the issue is (e.g. ``missing_header:x-frame-options``).
    identity: str
    #: Where it is (an origin, an endpoint or a source location).
    scope: str

    @property
    def group_key(self) -> str:
        """Readable, deterministic key; unique per assessment."""
        return f"{self.finding_type}|{self.rule.value}|{self.identity}|{self.scope}"


# --- normalization -----------------------------------------------------------


def normalize_text(value: Any) -> str:
    return _WHITESPACE.sub(" ", str(value or "")).strip().lower()


def split_method(component: str) -> tuple[str | None, str]:
    """``"GET http://x/a"`` -> ``("GET", "http://x/a")``."""
    text = str(component or "").strip()
    match = _METHOD_PREFIX.match(text)
    if match:
        return match.group(1).upper(), match.group(2).strip()
    return None, text


def _is_http_url(text: str) -> bool:
    return text.lower().startswith(("http://", "https://"))


def normalize_endpoint(component: str, *, keep_method: bool = False) -> str:
    """A URL-ish component in a canonical, comparable form.

    Scheme and host are lowercased, the fragment and a trailing ``/`` are
    dropped; the path and query are kept as they are (they can be
    meaningful). Anything that is not an http(s) URL - a file path, a source
    location - is only whitespace/case normalized.
    """
    method, rest = split_method(component)
    if _is_http_url(rest):
        parts = urlsplit(rest)
        path = parts.path.rstrip("/")
        normalized = f"{parts.scheme.lower()}://{parts.netloc.lower()}{path}"
        if parts.query:
            normalized += f"?{parts.query}"
    else:
        normalized = normalize_text(rest)
    if keep_method and method:
        return f"{method} {normalized}"
    return normalized


def origin_of(component: str) -> str:
    """``scheme://host[:port]`` of a URL component, else the normalized component."""
    _, rest = split_method(component)
    if _is_http_url(rest):
        parts = urlsplit(rest)
        return f"{parts.scheme.lower()}://{parts.netloc.lower()}"
    return normalize_endpoint(rest)


def _payload(evidence: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = evidence.get("evidence_payload")
    return payload if isinstance(payload, Mapping) else {}


def rule_id_of(evidence: Mapping[str, Any]) -> str | None:
    rule_id = _payload(evidence).get("rule_id")
    return str(rule_id).strip() if rule_id not in (None, "") else None


def missing_header(evidence: Mapping[str, Any]) -> str | None:
    """The response header a security record reports as absent, if it is one."""
    if evidence.get("finding_type") != "security":
        return None
    source = str(evidence.get("source") or "")
    rule_id = rule_id_of(evidence)
    if not rule_id:
        return None
    if source == "api_probe" and rule_id.startswith(API_PROBE_MISSING_PREFIX):
        header = rule_id[len(API_PROBE_MISSING_PREFIX):].strip().lower()
        return API_PROBE_HEADER_ALIASES.get(header, header) or None
    if source == "zap" and rule_id in ZAP_MISSING_HEADER_RULES:
        title = normalize_text(evidence.get("title"))
        if any(marker in title for marker in _MISSING_TITLE_MARKERS):
            return ZAP_MISSING_HEADER_RULES[rule_id]
    return None


# --- keys ----------------------------------------------------------------------


def correlation_key(evidence: Mapping[str, Any]) -> CorrelationKey:
    """The one key this evidence record correlates on."""
    finding_type = str(evidence.get("finding_type") or "")
    source = normalize_text(evidence.get("source"))
    title = normalize_text(evidence.get("title"))
    component = str(evidence.get("target_component") or "")

    if finding_type == "security":
        header = missing_header(evidence)
        if header:
            return CorrelationKey(
                CorrelationRule.SAME_MISSING_HEADER_AND_ORIGIN,
                finding_type,
                f"missing_header:{header}",
                origin_of(component),
            )
        rule_id = rule_id_of(evidence)
        if rule_id:
            scope = origin_of(component)
            parameter = normalize_text(_payload(evidence).get("parameter"))
            if parameter:
                scope = f"{scope}#param={parameter}"
            return CorrelationKey(
                CorrelationRule.SAME_SCANNER_RULE_AND_ORIGIN,
                finding_type,
                f"{source}:{rule_id}:{title}",
                scope,
            )
        return CorrelationKey(
            CorrelationRule.SAME_NORMALIZED_IDENTITY,
            finding_type,
            f"{source}:{title}",
            normalize_endpoint(component),
        )

    category = normalize_text(evidence.get("category"))
    return CorrelationKey(
        CorrelationRule.SAME_QA_CHECK_AND_COMPONENT,
        finding_type,
        f"{category}:{title}",
        normalize_endpoint(component, keep_method=True),
    )
