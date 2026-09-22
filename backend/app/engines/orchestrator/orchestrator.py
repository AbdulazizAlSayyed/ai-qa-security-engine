"""The assessment orchestrator.

Sequences the whole pipeline for one registered target::

    validate -> created -> running -> qa_running -> security_running
             -> normalizing -> completed        (or -> failed)

It controls lifecycle, state, sequencing, execution, result collection,
normalization and persistence. It does **not** interpret findings, rate
severity, invent evidence or call any AI - those belong to later phases.

It talks only to narrow ports, never to Playwright, ZAP, FastAPI or MongoDB
directly:

* a **target lookup** (the existing ``TargetService``),
* a **QA runner** and a **security runner** (the existing ``QaService`` and
  ``SecurityService``, which run the real engines and persist the raw runs),
* an **assessment store** (MongoDB in production, a fake in unit tests).

That keeps the orchestrator free of framework and database code, and means
a pipeline run produces exactly the same raw ``qa_runs`` / ``security_runs``
documents as a standalone run would.

Failure semantics - the distinction that matters most here:

* A target with failing tests or security findings is a **successful**
  assessment. Those are the output.
* An engine that cannot execute is a **stage failure**. It is recorded on
  the assessment, and the other stage still runs, so one broken tool does
  not throw away the other's evidence. The assessment completes with
  ``partial=True``.
* Only when *neither* engine could execute, or the orchestration itself
  breaks (persistence, an illegal transition), does the assessment become
  ``failed``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

from app.engines.orchestrator.models import AssessmentState, StageStatus
from app.engines.orchestrator.normalizer import (
    normalize_assessment,
    security_coverage,
    summarise,
)
from app.engines.orchestrator.state_machine import AssessmentStateMachine, utc_now

logger = logging.getLogger(__name__)

#: A full assessment drives a browser and a web scanner, so it needs a UI.
ASSESSABLE_TARGET_TYPES: frozenset[str] = frozenset({"web_application", "web_and_api"})


# --- errors --------------------------------------------------------------


class AssessmentError(Exception):
    """Base class for orchestration failures."""


class TargetNotAssessableError(AssessmentError):
    """The target exists but a full assessment cannot legitimately run."""


class AssessmentPersistenceError(AssessmentError):
    """The assessment or its evidence could not be stored or read back."""


class AssessmentOrchestrationError(AssessmentError):
    """The orchestrator itself broke - a bug, not a finding about the target."""


# --- ports -----------------------------------------------------------------


class TargetLookup(Protocol):
    async def get(self, target_id: str) -> dict[str, Any]: ...


class StageRunner(Protocol):
    """Runs one engine against a registered target and returns the stored run."""

    async def run(self, target_id: str) -> dict[str, Any]: ...


class AssessmentStore(Protocol):
    async def create(self, document: dict[str, Any]) -> str: ...

    async def update(
        self,
        assessment_id: str,
        fields: dict[str, Any],
        transition: dict[str, Any] | None = None,
    ) -> None: ...

    async def insert_evidence(self, documents: list[dict[str, Any]]) -> None: ...

    async def get(self, assessment_id: str) -> dict[str, Any]: ...


# --- helpers ---------------------------------------------------------------


@dataclass
class StageOutcome:
    """What one engine stage did."""

    status: StageStatus
    run: dict[str, Any] | None = None
    error: str | None = None

    @property
    def executed(self) -> bool:
        return self.status is StageStatus.COMPLETED

    def fields(self, prefix: str) -> dict[str, Any]:
        return {
            f"{prefix}_status": self.status.value,
            f"{prefix}_run_id": (self.run or {}).get("id"),
            f"{prefix}_run_status": (self.run or {}).get("status"),
            f"{prefix}_error": self.error,
        }


def require_assessable(target: dict[str, Any]) -> None:
    """Refuse targets a full assessment cannot legitimately run against."""
    name = target.get("name", "target")

    if not target.get("enabled", False):
        raise TargetNotAssessableError(
            f"Target {name!r} is disabled. Enable it before running an assessment."
        )

    target_type = str(target.get("type", ""))
    if target_type not in ASSESSABLE_TARGET_TYPES:
        supported = ", ".join(sorted(ASSESSABLE_TARGET_TYPES))
        raise TargetNotAssessableError(
            f"An assessment drives a browser and a web scanner, so it needs a web "
            f"target. Target {name!r} has type {target_type!r}; supported types are "
            f"{supported}."
        )

    if not (target.get("base_url") or "").strip():
        raise TargetNotAssessableError(
            f"Target {name!r} has no base_url, so there is nothing to assess."
        )


def _describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


# --- the orchestrator ------------------------------------------------------


class AssessmentOrchestrator:
    """Runs QA then security against a registered target, then normalizes."""

    def __init__(
        self,
        *,
        targets: TargetLookup,
        qa: StageRunner,
        security: StageRunner,
        store: AssessmentStore,
    ) -> None:
        self._targets = targets
        self._qa = qa
        self._security = security
        self._store = store

    async def run(self, target_id: str) -> dict[str, Any]:
        """Execute one full assessment and return it as stored.

        Raises the registry's own errors for an unknown or malformed target
        id, :class:`TargetNotAssessableError` for a target that may not be
        assessed - in both cases before anything is created - and
        :class:`AssessmentPersistenceError` /
        :class:`AssessmentOrchestrationError` when the platform itself fails.
        """
        # Target lookup goes through the registry, never around it.
        target = await self._targets.get(target_id)
        require_assessable(target)
        name = target.get("name", "")
        logger.info("Assessment target validated: %s (%s)", target.get("id"), name)

        machine = AssessmentStateMachine(message=f"Assessment created for target {name!r}")
        created_at = machine.history[0].timestamp
        assessment_id = await self._store.create(
            {
                # Snapshot: renaming or repointing the target later never
                # rewrites this historical record.
                "target_id": target["id"],
                "target_name": name,
                "target_base_url": (target.get("base_url") or "").strip(),
                "target_api_url": (target.get("api_url") or "").strip() or None,
                "target_type": target.get("type", ""),
                "status": machine.state.value,
                "state_history": machine.history_documents(),
                "created_at": created_at,
                "updated_at": created_at,
                "started_at": None,
                "finished_at": None,
                "duration_ms": None,
                **StageOutcome(StageStatus.PENDING).fields("qa"),
                **StageOutcome(StageStatus.PENDING).fields("security"),
                "partial": False,
                "security_coverage": [],
                "evidence_count": 0,
                "summary": summarise(None, None, 0),
                "error": None,
            }
        )
        logger.info("Assessment %s created for target %s", assessment_id, target["id"])

        clock_start = time.perf_counter()
        try:
            await self._pipeline(assessment_id, target_id, machine, clock_start)
        except AssessmentPersistenceError as exc:
            await self._mark_failed(assessment_id, machine, clock_start, _describe(exc))
            raise
        except Exception as exc:
            logger.exception("Assessment %s: orchestration error", assessment_id)
            await self._mark_failed(assessment_id, machine, clock_start, _describe(exc))
            raise AssessmentOrchestrationError(
                f"Assessment {assessment_id} failed inside the orchestrator: "
                f"{_describe(exc)}"
            ) from exc

        return await self._store.get(assessment_id)

    # --- stages ------------------------------------------------------------

    async def _pipeline(
        self,
        assessment_id: str,
        target_id: str,
        machine: AssessmentStateMachine,
        clock_start: float,
    ) -> None:
        await self._advance(
            assessment_id,
            machine,
            AssessmentState.RUNNING,
            "Pipeline started",
            started_at=utc_now(),
        )

        await self._advance(
            assessment_id,
            machine,
            AssessmentState.QA_RUNNING,
            "QA engine started",
            qa_status=StageStatus.RUNNING.value,
        )
        qa = await self._run_stage("QA", self._qa, assessment_id, target_id)

        await self._advance(
            assessment_id,
            machine,
            AssessmentState.SECURITY_RUNNING,
            f"QA stage {qa.status.value}; security engine started",
            **qa.fields("qa"),
            security_status=StageStatus.RUNNING.value,
        )
        security = await self._run_stage(
            "Security", self._security, assessment_id, target_id
        )

        if not qa.executed and not security.executed:
            # Nothing ran, so there is nothing to normalize or report.
            reason = (
                f"Neither engine could execute. QA: {qa.error}. Security: {security.error}."
            )
            await self._store.update(
                assessment_id, {**security.fields("security")}, None
            )
            await self._mark_failed(assessment_id, machine, clock_start, reason)
            return

        await self._advance(
            assessment_id,
            machine,
            AssessmentState.NORMALIZING,
            "Evidence normalization started",
            **security.fields("security"),
        )
        logger.info("Assessment %s: normalization started", assessment_id)

        evidence = normalize_assessment(assessment_id, qa.run, security.run)
        if evidence:
            await self._store.insert_evidence([item.to_document() for item in evidence])
        logger.info(
            "Assessment %s: normalization completed, %d evidence records",
            assessment_id,
            len(evidence),
        )

        partial = not (qa.executed and security.executed)
        failed_stages = [
            label for label, stage in (("QA", qa), ("security", security)) if not stage.executed
        ]
        message = f"{len(evidence)} evidence records normalized"
        if partial:
            message += f"; partial execution ({', '.join(failed_stages)} stage failed)"

        await self._advance(
            assessment_id,
            machine,
            AssessmentState.COMPLETED,
            message,
            finished_at=utc_now(),
            duration_ms=int((time.perf_counter() - clock_start) * 1000),
            partial=partial,
            security_coverage=security_coverage(security.run),
            evidence_count=len(evidence),
            summary=summarise(qa.run, security.run, len(evidence)),
        )
        logger.info(
            "Assessment %s completed: evidence=%d partial=%s qa=%s security=%s",
            assessment_id,
            len(evidence),
            partial,
            qa.status.value,
            security.status.value,
        )

    async def _run_stage(
        self, label: str, runner: StageRunner, assessment_id: str, target_id: str
    ) -> StageOutcome:
        """Run one engine through its service. Never raises.

        A stage fails when its service raised (no run exists) or when the
        stored run records that the engine itself could not execute. Failing
        tests and security findings are *not* stage failures.
        """
        logger.info("Assessment %s: %s stage started", assessment_id, label)
        try:
            run = await runner.run(target_id)
        except Exception as exc:
            logger.exception("Assessment %s: %s stage failed", assessment_id, label)
            return StageOutcome(StageStatus.FAILED, None, _describe(exc))

        if run.get("error"):
            logger.warning(
                "Assessment %s: %s engine reported it could not execute: %s",
                assessment_id,
                label,
                run["error"],
            )
            # The run is real and stored, so it stays referenced.
            return StageOutcome(StageStatus.FAILED, run, str(run["error"]))

        logger.info(
            "Assessment %s: %s stage completed, run %s (%s)",
            assessment_id,
            label,
            run.get("id"),
            run.get("status"),
        )
        return StageOutcome(StageStatus.COMPLETED, run, None)

    # --- state + persistence -------------------------------------------

    async def _advance(
        self,
        assessment_id: str,
        machine: AssessmentStateMachine,
        state: AssessmentState,
        message: str,
        **fields: Any,
    ) -> None:
        """Transition, and persist the new state with its history entry."""
        transition = machine.transition_to(state, message)
        await self._store.update(
            assessment_id,
            {"status": state.value, **fields},
            transition.to_document(),
        )

    async def _mark_failed(
        self,
        assessment_id: str,
        machine: AssessmentStateMachine,
        clock_start: float,
        reason: str,
    ) -> None:
        """Best effort: record the failure. Never masks the original error."""
        transition = machine.fail(reason)
        if transition is None:
            return
        logger.error("Assessment %s failed: %s", assessment_id, reason)
        try:
            await self._store.update(
                assessment_id,
                {
                    "status": AssessmentState.FAILED.value,
                    "error": reason,
                    "finished_at": transition.timestamp,
                    "duration_ms": int((time.perf_counter() - clock_start) * 1000),
                },
                transition.to_document(),
            )
        except Exception:  # pragma: no cover - the store is already failing
            logger.exception(
                "Assessment %s: could not record the failure either", assessment_id
            )
