"""Test doubles for the AI layer (not collected by pytest).

``FakeProvider`` is an :class:`AIProvider` that never touches the network.
By default it answers like a well-behaved model: it reads the evidence block
out of the prompt it was given and cites only references it saw there.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from app.engines.ai.provider import AIProvider, AIProviderError, ProviderResult

_EVIDENCE_BLOCK = re.compile(
    r"BEGIN ASSESSMENT EVIDENCE\n(.*?)\nEND ASSESSMENT EVIDENCE", re.DOTALL
)


def evidence_in(user_prompt: str) -> list[dict[str, Any]]:
    match = _EVIDENCE_BLOCK.search(user_prompt)
    assert match, "the user prompt has no evidence block"
    return json.loads(match.group(1))


def grounded_answer(user_prompt: str) -> dict[str, Any]:
    """A valid, evidence-grounded answer built only from the supplied evidence."""
    evidence = evidence_in(user_prompt)
    findings: list[dict[str, Any]] = []

    failed_qa = [e for e in evidence if e["finding_type"] == "qa" and e["status"] == "failed"]
    if failed_qa:
        findings.append(
            {
                "finding_id": f"AI-F-{len(findings) + 1:03d}",
                "type": "qa",
                "status": "supported",
                "title": failed_qa[0]["title"],
                "description": f"The check reported: {failed_qa[0]['actual']}.",
                "impact": "Users may see incorrect behaviour.",
                "confidence": "high",
                "tool_severity": None,
                "evidence_ids": [e["id"] for e in failed_qa],
                "uncertainty": "The evidence does not show the root cause.",
            }
        )

    by_severity: dict[str, list[dict[str, Any]]] = {}
    for item in evidence:
        if item["finding_type"] == "security" and item.get("tool_severity"):
            by_severity.setdefault(item["tool_severity"], []).append(item)
    for severity, items in by_severity.items():
        findings.append(
            {
                "finding_id": f"AI-F-{len(findings) + 1:03d}",
                "type": "security",
                "status": "supported" if severity != "informational" else "insufficient_evidence",
                "title": f"{severity} scanner findings",
                "description": "The scanner reported these observations.",
                "impact": "Interpretation: may weaken defence in depth.",
                "confidence": "medium",
                "tool_severity": severity,
                "evidence_ids": [e["id"] for e in items],
                "uncertainty": "The evidence does not establish exploitability.",
            }
        )

    return {
        "overall_assessment": f"{len(evidence)} evidence records reviewed.",
        "findings": findings,
        "evidence_gaps": ["Authentication behaviour was not exercised."],
        "limitations": ["Passive evidence only."],
    }


class FakeProvider(AIProvider):
    """Records prompts; answers via ``respond`` or raises ``error``."""

    name = "fake"

    def __init__(
        self,
        respond: Callable[[str], str] | None = None,
        *,
        error: Exception | None = None,
        model: str = "fake-model",
    ) -> None:
        self.respond = respond or (lambda user: json.dumps(grounded_answer(user)))
        self.error = error
        self._model = model
        self.calls: list[dict[str, str]] = []

    @property
    def model(self) -> str:
        return self._model

    async def analyze(self, *, system_prompt: str, user_prompt: str) -> ProviderResult:
        self.calls.append({"system": system_prompt, "user": user_prompt})
        if self.error is not None:
            raise self.error
        return ProviderResult(
            text=self.respond(user_prompt), model=self._model, usage={"input_tokens": 1}
        )


__all__ = ["AIProviderError", "FakeProvider", "evidence_in", "grounded_answer"]
