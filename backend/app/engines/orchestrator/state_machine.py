"""The assessment state machine.

Small on purpose. Its whole job is to make the lifecycle explicit and
recorded: which state the assessment is in, how it got there, and when. The
orchestrator drives it; this class refuses illegal moves so a bug in the
sequencing shows up immediately instead of producing a plausible but wrong
history.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.engines.orchestrator.models import (
    FINAL_STATES,
    AssessmentState,
    StateTransition,
)

#: Which states may follow which. The pipeline is strictly linear, and
#: failure is reachable from any state that has not already finished.
#:
#: ``analyzing`` (Phase 5) is entered only from ``completed``, when a user
#: explicitly asks for AI analysis of a finished technical assessment, and it
#: always returns to ``completed`` - whether the analysis succeeded or not.
#: AI trouble never turns a successful assessment into ``failed``, and the
#: pipeline itself (``normalizing``) cannot enter ``analyzing``.
ALLOWED_TRANSITIONS: dict[AssessmentState, frozenset[AssessmentState]] = {
    AssessmentState.CREATED: frozenset({AssessmentState.RUNNING, AssessmentState.FAILED}),
    AssessmentState.RUNNING: frozenset(
        {AssessmentState.QA_RUNNING, AssessmentState.FAILED}
    ),
    AssessmentState.QA_RUNNING: frozenset(
        {AssessmentState.SECURITY_RUNNING, AssessmentState.FAILED}
    ),
    AssessmentState.SECURITY_RUNNING: frozenset(
        {AssessmentState.NORMALIZING, AssessmentState.FAILED}
    ),
    AssessmentState.NORMALIZING: frozenset(
        {AssessmentState.COMPLETED, AssessmentState.FAILED}
    ),
    AssessmentState.ANALYZING: frozenset({AssessmentState.COMPLETED}),
    AssessmentState.COMPLETED: frozenset({AssessmentState.ANALYZING}),
    AssessmentState.FAILED: frozenset(),
}


class IllegalStateTransition(RuntimeError):
    """The orchestrator tried to move somewhere the lifecycle forbids."""


def is_allowed(current: AssessmentState, target: AssessmentState) -> bool:
    """The transition table, for callers that move a *stored* assessment."""
    return target in ALLOWED_TRANSITIONS[current]


def utc_now() -> datetime:
    """UTC at MongoDB's millisecond precision, as the other engines use."""
    now = datetime.now(timezone.utc)
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


class AssessmentStateMachine:
    """Tracks the current state and the full ordered history."""

    def __init__(self, message: str | None = None) -> None:
        self._state = AssessmentState.CREATED
        self._history: list[StateTransition] = [
            StateTransition(
                state=AssessmentState.CREATED, timestamp=utc_now(), message=message
            )
        ]

    @property
    def state(self) -> AssessmentState:
        return self._state

    @property
    def history(self) -> list[StateTransition]:
        return list(self._history)

    @property
    def is_final(self) -> bool:
        return self._state in FINAL_STATES

    def can_transition_to(self, state: AssessmentState) -> bool:
        return state in ALLOWED_TRANSITIONS[self._state]

    def transition_to(
        self, state: AssessmentState, message: str | None = None
    ) -> StateTransition:
        """Move to ``state``, recording when and why."""
        if not self.can_transition_to(state):
            allowed = ALLOWED_TRANSITIONS[self._state]
            raise IllegalStateTransition(
                f"Cannot move from {self._state.value!r} to {state.value!r}. "
                f"Allowed: {', '.join(sorted(s.value for s in allowed)) or 'none'}."
            )

        transition = StateTransition(state=state, timestamp=utc_now(), message=message)
        self._history.append(transition)
        self._state = state
        return transition

    def fail(self, reason: str) -> StateTransition | None:
        """Move to FAILED from wherever we are. ``None`` if already finished."""
        if self.is_final:
            return None
        return self.transition_to(AssessmentState.FAILED, message=reason)

    def history_documents(self) -> list[dict]:
        return [transition.to_document() for transition in self._history]
