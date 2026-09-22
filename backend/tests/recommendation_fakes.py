"""Test doubles for Phase 8 (not collected by pytest).

``recommendation_respond`` is a FakeProvider ``respond`` function: it answers
the Phase 5 analysis prompt with the existing grounded fake answer, and the
Phase 8 recommendation prompt with a grounded fake recommendation set built
only from the issues it was shown. It is a FAKE, never a real model.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from tests.ai_fakes import grounded_answer

_ISSUES = re.compile(r"BEGIN ASSESSMENT ISSUES\n(.*?)\nEND ASSESSMENT ISSUES", re.DOTALL)


def issues_in(user_prompt: str) -> list[dict[str, Any]]:
    match = _ISSUES.search(user_prompt)
    assert match, "the user prompt has no issues block"
    return json.loads(match.group(1))


def is_recommendation_prompt(user_prompt: str) -> bool:
    return "BEGIN ASSESSMENT ISSUES" in user_prompt


def grounded_recommendations(user_prompt: str) -> dict[str, Any]:
    recommendations = []
    for issue in issues_in(user_prompt):
        refs = issue["evidence_ids"]
        if not refs:
            continue
        component = (issue["affected_components"] or [issue["scope"]])[0]
        recommendations.append(
            {
                "issue_id": issue["issue_id"],
                "related_issue_ids": [],
                "type": "configuration_change" if issue["type"] == "security" else "qa_test_improvement",
                "title": f"Review: {issue['title']}",
                "description": "Advisory: review the configuration behind the cited evidence.",
                "rationale": "The cited evidence shows the observation this advice addresses.",
                "confidence": "medium",
                "evidence_ids": refs,
                "retest": {
                    "target_component": component,
                    "evidence_ids": refs[:1],
                    "preconditions": [],
                    "expected_result": "The same check no longer reports the observation.",
                    "pass_criteria": "The re-run check does not report the issue again.",
                    "fail_criteria": "The re-run check reports the issue again.",
                },
            }
        )
    return {"recommendations": recommendations}


def recommendation_respond(
    mutate: Callable[[dict[str, Any], str], Any] | None = None,
) -> Callable[[str], str]:
    """Analysis prompts get the Phase 5 fake; recommendation prompts get ours.

    ``mutate(answer, prompt)`` may alter the recommendation answer (or return
    a replacement, e.g. a raw string) to exercise validation.
    """

    def respond(user_prompt: str) -> str:
        if not is_recommendation_prompt(user_prompt):
            return json.dumps(grounded_answer(user_prompt))
        answer = grounded_recommendations(user_prompt)
        if mutate is not None:
            replaced = mutate(answer, user_prompt)
            if replaced is not None:
                return replaced if isinstance(replaced, str) else json.dumps(replaced)
        return json.dumps(answer)

    return respond
