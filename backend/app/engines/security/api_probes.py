"""Generic, non-destructive API security probes.

Every probe here is safe by construction: it only ever sends ``GET``,
``HEAD`` or ``OPTIONS``. Nothing is created, modified or deleted on the
target, no credentials are guessed, and nothing is fuzzed. The probes read
what the application volunteers about itself and report it.

Severity is assigned conservatively. A missing ``Referrer-Policy`` is not a
breach; calling it one would train whoever reads the report to ignore the
report. The genuinely dangerous combination - an API that reflects an
arbitrary ``Origin`` *and* allows credentials - is the only thing here that
can reach ``high``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from app.engines.security.models import (
    ComponentResult,
    ComponentStatus,
    SecurityFinding,
    Severity,
)

logger = logging.getLogger(__name__)

COMPONENT_NAME = "api_probes"
AUTHZ_COMPONENT_NAME = "authorization_probes"

#: A deliberately invalid, non-routable origin. Used only to observe how the
#: target's CORS policy answers an origin it has never seen.
PROBE_ORIGIN = "https://qa-security-probe.invalid"

#: Methods that are unsafe to send, and are therefore only ever *reported*
#: when the target advertises them. The engine never issues them.
UNSAFE_METHODS = {"PUT", "DELETE", "PATCH", "TRACE", "TRACK", "CONNECT"}


@dataclass(frozen=True)
class ProbeConfig:
    timeout_seconds: float = 10.0
    #: Local targets routinely use self-signed certificates.
    verify_tls: bool = False
    probe_origin: str = PROBE_ORIGIN


def _finding(
    name: str,
    severity: Severity,
    *,
    url: str,
    rule_id: str,
    description: str,
    evidence: str | None = None,
    solution: str | None = None,
    reference: str | None = None,
    cwe: str | None = None,
    method: str | None = None,
) -> SecurityFinding:
    return SecurityFinding(
        source="api_probe",
        rule_id=rule_id,
        name=name,
        severity=severity,
        description=description,
        confidence="high",
        url=url,
        method=method,
        evidence=evidence,
        solution=solution,
        reference=reference,
        cwe=cwe,
    )


# --- individual probes -------------------------------------------------


def probe_security_headers(
    url: str, headers: dict[str, str], is_https: bool
) -> list[SecurityFinding]:
    """Report response headers that harden a browser client, when absent."""
    lower = {key.lower(): value for key, value in headers.items()}
    findings: list[SecurityFinding] = []

    expectations: list[tuple[str, Severity, str, str]] = [
        (
            "x-content-type-options",
            Severity.LOW,
            "Missing X-Content-Type-Options header",
            "Without 'nosniff' a browser may MIME-sniff a response and treat it as a "
            "different content type than intended.",
        ),
        (
            "content-security-policy",
            Severity.LOW,
            "Missing Content-Security-Policy header",
            "A CSP constrains what a browser will load and execute for this response.",
        ),
        (
            "x-frame-options",
            Severity.LOW,
            "Missing X-Frame-Options header",
            "Without a framing policy the response may be embedded by another site.",
        ),
        (
            "referrer-policy",
            Severity.INFORMATIONAL,
            "Missing Referrer-Policy header",
            "The default referrer behaviour may leak URLs to third parties.",
        ),
    ]

    for header, severity, name, description in expectations:
        if header not in lower:
            findings.append(
                _finding(
                    name,
                    severity,
                    url=url,
                    rule_id=f"api-probe-missing-{header}",
                    description=description,
                    evidence=f"Response did not include a '{header}' header.",
                    solution=f"Set an appropriate '{header}' response header.",
                    cwe="693",
                )
            )

    # HSTS only means anything over TLS; flagging it on plain HTTP would be
    # noise, so the transport itself is the finding instead.
    if is_https and "strict-transport-security" not in lower:
        findings.append(
            _finding(
                "Missing Strict-Transport-Security header",
                Severity.MEDIUM,
                url=url,
                rule_id="api-probe-missing-hsts",
                description="HTTPS is served without instructing browsers to stay on HTTPS.",
                evidence="Response over TLS did not include 'strict-transport-security'.",
                solution="Send Strict-Transport-Security with an appropriate max-age.",
                cwe="319",
            )
        )

    return findings


def probe_server_disclosure(url: str, headers: dict[str, str]) -> list[SecurityFinding]:
    """Report unnecessary advertising of server software and versions."""
    lower = {key.lower(): value for key, value in headers.items()}
    findings: list[SecurityFinding] = []

    for header in ("server", "x-powered-by"):
        value = lower.get(header)
        if not value:
            continue
        # A bare product name is a smaller problem than one with a version.
        has_version = any(char.isdigit() for char in value)
        findings.append(
            _finding(
                f"Server software disclosed via {header}",
                Severity.LOW if has_version else Severity.INFORMATIONAL,
                url=url,
                rule_id=f"api-probe-disclosure-{header}",
                description=(
                    "The response advertises the server technology"
                    + (" and its version" if has_version else "")
                    + ", which helps an attacker target known issues."
                ),
                evidence=f"{header}: {value}",
                solution=f"Remove or generalise the '{header}' response header.",
                cwe="200",
            )
        )

    return findings


def probe_cors(url: str, headers: dict[str, str], probe_origin: str) -> list[SecurityFinding]:
    """Assess how the target answers an origin it has never seen.

    The engine only *observes* the response to a normal GET carrying an
    ``Origin`` header. It never attempts to use a weak policy.
    """
    lower = {key.lower(): value for key, value in headers.items()}
    allow_origin = lower.get("access-control-allow-origin")
    allow_credentials = (lower.get("access-control-allow-credentials") or "").lower() == "true"

    if not allow_origin:
        return []

    reflects_probe = allow_origin.strip() == probe_origin
    is_wildcard = allow_origin.strip() == "*"

    if reflects_probe and allow_credentials:
        return [
            _finding(
                "CORS reflects any origin and allows credentials",
                Severity.HIGH,
                url=url,
                rule_id="api-probe-cors-reflect-credentials",
                description=(
                    "The API echoed an arbitrary origin back in "
                    "Access-Control-Allow-Origin while also allowing credentials, so any "
                    "site a logged-in user visits could read authenticated responses."
                ),
                evidence=(
                    f"Sent Origin: {probe_origin} -> "
                    f"access-control-allow-origin: {allow_origin}; "
                    "access-control-allow-credentials: true"
                ),
                solution="Allow only an explicit list of trusted origins when credentials are enabled.",
                reference="https://owasp.org/www-community/attacks/CORS_OriginHeaderScrutiny",
                cwe="942",
            )
        ]

    if is_wildcard and allow_credentials:
        return [
            _finding(
                "CORS wildcard combined with credentials",
                Severity.HIGH,
                url=url,
                rule_id="api-probe-cors-wildcard-credentials",
                description=(
                    "Access-Control-Allow-Origin is '*' while credentials are allowed. "
                    "Browsers reject this combination, which usually means the policy is "
                    "misconfigured and the intent was overly permissive."
                ),
                evidence=f"access-control-allow-origin: *; access-control-allow-credentials: true",
                solution="Name the trusted origins explicitly instead of using a wildcard.",
                cwe="942",
            )
        ]

    if reflects_probe:
        return [
            _finding(
                "CORS reflects arbitrary origins",
                Severity.MEDIUM,
                url=url,
                rule_id="api-probe-cors-reflect",
                description=(
                    "The API echoed an unknown origin back, so any site may read "
                    "unauthenticated responses from it."
                ),
                evidence=f"Sent Origin: {probe_origin} -> access-control-allow-origin: {allow_origin}",
                solution="Restrict Access-Control-Allow-Origin to trusted origins.",
                cwe="942",
            )
        ]

    if is_wildcard:
        return [
            _finding(
                "CORS allows any origin",
                Severity.LOW,
                url=url,
                rule_id="api-probe-cors-wildcard",
                description=(
                    "Access-Control-Allow-Origin is '*'. Acceptable for genuinely public "
                    "data; a problem if any response is meant to be private."
                ),
                evidence="access-control-allow-origin: *",
                solution="Confirm every response served here is intended to be public.",
                cwe="942",
            )
        ]

    return []


def probe_http_methods(url: str, headers: dict[str, str]) -> list[SecurityFinding]:
    """Report methods the target *advertises*. None of them are sent."""
    lower = {key.lower(): value for key, value in headers.items()}
    advertised_raw = lower.get("allow") or lower.get("access-control-allow-methods") or ""
    advertised = {
        method.strip().upper() for method in advertised_raw.split(",") if method.strip()
    }
    if not advertised:
        return []

    findings: list[SecurityFinding] = []

    if advertised & {"TRACE", "TRACK"}:
        findings.append(
            _finding(
                "TRACE/TRACK method advertised",
                Severity.MEDIUM,
                url=url,
                rule_id="api-probe-trace-enabled",
                description=(
                    "TRACE echoes the request back and has been used for Cross-Site "
                    "Tracing. It is almost never needed in production."
                ),
                evidence=f"Advertised methods: {advertised_raw}",
                solution="Disable TRACE and TRACK on the server.",
                cwe="16",
                method="OPTIONS",
            )
        )

    state_changing = advertised & (UNSAFE_METHODS - {"TRACE", "TRACK", "CONNECT"})
    if state_changing:
        findings.append(
            _finding(
                "State-changing HTTP methods advertised",
                Severity.INFORMATIONAL,
                url=url,
                rule_id="api-probe-state-changing-methods",
                description=(
                    "The endpoint advertises methods that modify data. This is normal "
                    "for a REST API and is recorded for context only - the engine did "
                    "not send any of them."
                ),
                evidence=f"Advertised methods: {advertised_raw}",
                solution="Ensure each method enforces authentication and authorization.",
                method="OPTIONS",
            )
        )

    return findings


# --- component driver --------------------------------------------------


def run_api_probes(api_url: str, config: ProbeConfig | None = None) -> ComponentResult:
    """Run every safe probe against the target's registered API URL.

    Blocking; the service calls it from a worker thread. Never raises.
    """
    config = config or ProbeConfig()
    started = time.perf_counter()
    findings: list[SecurityFinding] = []
    metadata: dict[str, Any] = {"probe_origin": config.probe_origin, "url": api_url}

    try:
        import httpx
    except Exception as exc:  # pragma: no cover - httpx is a hard dependency
        return ComponentResult(
            name=COMPONENT_NAME,
            status=ComponentStatus.FAILED,
            duration_ms=int((time.perf_counter() - started) * 1000),
            detail=f"HTTP client unavailable: {exc}",
            metadata=metadata,
        )

    is_https = urlparse(api_url).scheme == "https"
    metadata["is_https"] = is_https

    try:
        with httpx.Client(
            timeout=config.timeout_seconds,
            verify=config.verify_tls,
            follow_redirects=True,
        ) as client:
            # --- 1. reachability, carrying an unknown Origin so the same
            #        response also answers the CORS question.
            request_started = time.perf_counter()
            try:
                response = client.get(
                    api_url,
                    headers={"Origin": config.probe_origin, "Accept": "*/*"},
                )
            except Exception as exc:
                metadata.update(
                    {
                        "reachable": False,
                        "error": f"{type(exc).__name__}: {exc}",
                        "response_time_ms": int((time.perf_counter() - request_started) * 1000),
                    }
                )
                # The scanner worked; the target did not answer. That is an
                # observation about the target, not a scanner failure, but
                # no header-based probe can run without a response.
                return ComponentResult(
                    name=COMPONENT_NAME,
                    status=ComponentStatus.COMPLETED,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    detail="API did not respond; header-based probes were not applicable.",
                    findings=[],
                    metadata=metadata,
                )

            headers = dict(response.headers)
            metadata.update(
                {
                    "reachable": True,
                    "status_code": response.status_code,
                    "response_time_ms": int((time.perf_counter() - request_started) * 1000),
                    "headers": headers,
                    "error": None,
                }
            )

            findings.extend(probe_security_headers(api_url, headers, is_https))
            findings.extend(probe_server_disclosure(api_url, headers))
            findings.extend(probe_cors(api_url, headers, config.probe_origin))

            # --- 2. advertised methods, via OPTIONS only.
            try:
                options = client.request(
                    "OPTIONS",
                    api_url,
                    headers={
                        "Origin": config.probe_origin,
                        "Access-Control-Request-Method": "GET",
                    },
                )
                options_headers = dict(options.headers)
                metadata["options_status_code"] = options.status_code
                metadata["advertised_methods"] = (
                    options_headers.get("allow")
                    or options_headers.get("access-control-allow-methods")
                )
                findings.extend(probe_http_methods(api_url, options_headers))
            except Exception as exc:
                # A server that refuses OPTIONS is common; not a failure.
                metadata["options_error"] = f"{type(exc).__name__}: {exc}"

    except Exception as exc:
        logger.exception("API probes could not execute against %s", api_url)
        return ComponentResult(
            name=COMPONENT_NAME,
            status=ComponentStatus.FAILED,
            duration_ms=int((time.perf_counter() - started) * 1000),
            detail=f"{type(exc).__name__}: {exc}",
            metadata=metadata,
        )

    return ComponentResult(
        name=COMPONENT_NAME,
        status=ComponentStatus.COMPLETED,
        duration_ms=int((time.perf_counter() - started) * 1000),
        findings=findings,
        metadata=metadata,
    )


def skipped_api_probes(reason: str) -> ComponentResult:
    """The target has no API URL, so there is nothing to probe."""
    return ComponentResult(
        name=COMPONENT_NAME,
        status=ComponentStatus.SKIPPED,
        detail=reason,
    )


@dataclass(frozen=True)
class AuthorizationReadiness:
    """What the target's profile says about authenticated testing.

    Configuration read from the registry, passed in by the service. It is
    not evidence about the target and nothing here contacts it.
    """

    #: The operator declared this is their own test environment.
    owned_test_environment: bool = False
    #: The profile describes a way to authenticate.
    authentication_configured: bool = False
    #: Accounts that are enabled and whose credentials actually resolve.
    usable_accounts: int = 0
    #: Distinct roles among those accounts.
    distinct_roles: int = 0

    def missing(self) -> list[str]:
        """Everything still standing between this target and Phase 18.

        Reported in full rather than first-failure-only: an operator fixing
        the configuration would otherwise rediscover the next gap one run at
        a time.
        """
        gaps: list[str] = []
        if not self.owned_test_environment:
            gaps.append(
                "the target is not marked as an owned test environment"
            )
        if not self.authentication_configured:
            gaps.append("no authentication is configured for the target")
        if self.usable_accounts == 0:
            gaps.append("no enabled test account has resolvable credentials")
        elif self.distinct_roles < 2:
            gaps.append(
                "only one role is configured, and comparing two identities needs two"
            )
        return gaps


def authorization_probes_placeholder(
    readiness: AuthorizationReadiness | None = None,
) -> ComponentResult:
    """Authorization probing is architecturally present but never executed.

    Testing whether actor A can reach actor B's data needs two authorised
    identities and permission to use them. Phase 12 gave the registry
    somewhere to record both; no engine acts on them yet, so this still
    skips - an invented pass would be the worst possible answer here.

    What Phase 12 changes is the honesty of the reason. Previously every
    target got the same sentence whether it had no accounts, no
    authentication or no authorisation. Now the skip names what is actually
    missing, and a fully configured target is told that the engine itself is
    what has not arrived rather than being left looking misconfigured.
    """
    readiness = readiness or AuthorizationReadiness()
    gaps = readiness.missing()

    if gaps:
        detail = (
            "No authenticated probing was attempted: "
            + "; ".join(gaps)
            + ". Authorization testing arrives in a later phase."
        )
    else:
        detail = (
            "The target is configured for authenticated testing "
            f"({readiness.usable_accounts} usable account(s) across "
            f"{readiness.distinct_roles} role(s)), but the authorization engine "
            "is not implemented yet, so nothing was attempted."
        )

    return ComponentResult(
        name=AUTHZ_COMPONENT_NAME,
        status=ComponentStatus.SKIPPED,
        detail=detail,
        metadata={
            "owned_test_environment": readiness.owned_test_environment,
            "authentication_configured": readiness.authentication_configured,
            "usable_accounts": readiness.usable_accounts,
            "distinct_roles": readiness.distinct_roles,
        },
    )
