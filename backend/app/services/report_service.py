"""Report generation (Phase 10): read -> audit -> assemble -> render -> persist.

::

    Route -> ReportService
               |- loads (read-only): assessment, target, qa_run, security_run,
               |   evidence, ai_analysis_logs, correlation_groups, issues,
               |   recommendations, retests (+ retests' raw runs)
               |- engines/reporting/traceability.py   audit every stored reference
               |- engines/reporting/assembler.py      one normalized report model
               |- engines/reporting/html_renderer.py  self-contained HTML
               |- engines/reporting/pdf_renderer.py   ReportLab PDF
               |- engines/reporting/redaction.py      leak audit before storing
               '- writes: reports (+ the two files under REPORTS_ROOT)

Nothing is re-run: no scanner, browser, model, correlation, recommendation
or retest. A broken reference is never repaired - the attempt is recorded
as a failed report with the broken relationships and the API answers 409.
Regenerating from unchanged data returns the existing report (idempotent);
changed data (for example a new retest) produces the next ``REPORT-###``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.core.config import Settings
from app.engines.orchestrator.state_machine import utc_now
from app.engines.reporting.assembler import REPORT_VERSION, assemble, fingerprint
from app.engines.reporting.html_renderer import render_html
from app.engines.reporting.pdf_renderer import render_pdf
from app.engines.reporting.redaction import find_leaks, known_secrets
from app.engines.reporting.traceability import TraceInputs, audit, referenced_evidence_ids
from app.models import ai_analysis as analysis_model
from app.models import assessment as assessment_model
from app.models import correlation_group as group_model
from app.models import evidence as evidence_model
from app.models import issue as issue_model
from app.models import qa_run as qa_run_model
from app.models import recommendation as recommendation_model
from app.models import report as report_model
from app.models import retest as retest_model
from app.models import security_run as security_run_model
from app.models import target as target_model
from app.services.assessment_service import AssessmentNotFoundError, InvalidAssessmentIdError

logger = logging.getLogger(__name__)

REPORT_ID_PATTERN = re.compile(r"^REPORT-(\d{3,})$")
DEFAULT_LIST_LIMIT = 100
_NUMBER_ATTEMPTS = 5
MEDIA_TYPES = {"html": "text/html; charset=utf-8", "pdf": "application/pdf"}


class ReportServiceError(Exception):
    """Base class for report failures."""


class InvalidReportReferenceError(ReportServiceError):
    """Malformed REPORT-### (400)."""


class ReportNotFoundError(ReportServiceError):
    """Unknown report, or a format that was not produced (404)."""


class ReportPreconditionError(ReportServiceError):
    """The assessment is not in a reportable state, or a report is being generated (409)."""


class ReportTraceabilityError(ReportServiceError):
    """Stored references are broken; recorded as a failed report (409)."""

    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        errors = ((report.get("traceability") or {}).get("errors")) or []
        shown = "; ".join(f"{e['relationship']}: {e['source']} -> {e['reference']} ({e['problem']})" for e in errors[:5])
        more = f" and {len(errors) - 5} more" if len(errors) > 5 else ""
        super().__init__(
            f"{report.get('report_id')} was not generated: traceability audit failed with "
            f"{len(errors)} broken reference(s): {shown}{more}."
        )


class ReportGenerationFailedError(ReportServiceError):
    """Rendering, the leak audit or writing the files failed; recorded as failed (500)."""

    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        error = report.get("error") or {}
        super().__init__(f"{report.get('report_id')} failed ({error.get('category')}): {error.get('message')}")


class ReportArtifactIntegrityError(ReportServiceError):
    """A stored file is missing or does not match its recorded SHA-256 (500)."""


class ReportPersistenceError(ReportServiceError):
    """MongoDB failed (500)."""


def report_reference(number: int) -> str:
    return f"REPORT-{number:03d}"


def _oid(value: Any) -> ObjectId | None:
    return ObjectId(str(value)) if value and ObjectId.is_valid(str(value)) else None


class ReportService:
    def __init__(self, db: AsyncDatabase, settings: Settings) -> None:
        self._settings = settings
        self._assessments = assessment_model.get_collection(db)
        self._targets = target_model.get_collection(db)
        self._qa_runs = qa_run_model.get_collection(db)
        self._security_runs = security_run_model.get_collection(db)
        self._evidence = evidence_model.get_collection(db)
        self._analyses = analysis_model.get_collection(db)
        self._groups = group_model.get_collection(db)
        self._issues = issue_model.get_collection(db)
        self._recommendations = recommendation_model.get_collection(db)
        self._retests = retest_model.get_collection(db)
        self._reports = report_model.get_collection(db)

    # --- generation -----------------------------------------------------------------

    async def generate(self, assessment_id: str) -> tuple[dict[str, Any], bool]:
        """Return ``(report, reused)``."""
        started = time.perf_counter()
        assessment = await self._assessment(assessment_id)
        self._check_reportable(assessment)
        sources = await self._load(assessment)
        trace = audit(sources)
        now = utc_now()
        trace_doc = {**trace.as_dict(), "checked_at": now}

        model = assemble(
            assessment=assessment, target=sources.target, qa_run=sources.qa_run, security_run=sources.security_run,
            evidence=sources.evidence, analyses=sources.analyses, groups=sources.groups, issues=sources.issues,
            recommendations=sources.recommendations, retests=sources.retests, traceability=trace.as_dict(),
        )
        source_fp = fingerprint(model)
        dedupe = f"{assessment_id}|{REPORT_VERSION}|{source_fp}"
        base = {
            "assessment_id": assessment_id,
            "target_id": str(assessment.get("target_id")),
            "target_name": assessment.get("target_name"),
            "report_version": REPORT_VERSION,
            "source_fingerprint": source_fp,
            "source_snapshot": self._snapshot(assessment, model, sources),
            "traceability": trace_doc,
            "summary": model["summary"],
        }

        if not trace.ok:
            existing = await self._read_one({"assessment_id": assessment_id, "source_fingerprint": source_fp,
                                             "status": "failed", "error.category": "traceability"})
            if existing is not None:  # same broken data: no new record per click
                raise ReportTraceabilityError(report_model.document_to_response(existing))
            failed = await self._insert_numbered({
                **base, "status": "failed", "formats": [], "artifacts": {}, "created_at": now, "updated_at": now,
                "completed_at": now, "duration_ms": int((time.perf_counter() - started) * 1000),
                "error": {"category": "traceability", "message": f"{len(trace.errors)} broken reference(s); no report was rendered."},
            })
            logger.warning("Report %s: traceability failed for assessment %s (%d errors)", failed["report_id"], assessment_id, len(trace.errors))
            raise ReportTraceabilityError(report_model.document_to_response(failed))

        existing = await self._read_one({"dedupe_key": dedupe, "status": "completed"})
        if existing is not None:
            return report_model.document_to_response(existing), True

        await self._close_stale(assessment_id, now)
        try:
            reserved = await self._insert_numbered({
                **base, "dedupe_key": dedupe, "status": "running", "formats": [], "artifacts": {},
                "created_at": now, "updated_at": now, "completed_at": None, "duration_ms": None, "error": None,
            })
        except DuplicateKeyError as exc:
            concurrent = await self._read_one({"dedupe_key": dedupe, "status": "completed"})
            if concurrent is not None:
                return report_model.document_to_response(concurrent), True
            raise ReportPreconditionError("A report for this data is already being generated. Try again shortly.") from exc

        model["meta"].update({
            "report_id": reserved["report_id"],
            "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_fingerprint": source_fp,
        })
        try:
            fields = self._render_and_write(assessment_id, reserved["report_id"], model)
        except Exception as exc:  # never leave a report "running"
            category = getattr(exc, "category", "render_failed")
            message = str(exc) if category == "secret_leak" else f"The report could not be rendered or written ({type(exc).__name__})."
            logger.error("Report %s failed: %s", reserved["report_id"], message)
            fields = {"status": "failed", "error": {"category": category, "message": message}}

        finished = utc_now()
        fields.update({"completed_at": finished, "updated_at": finished, "duration_ms": int((time.perf_counter() - started) * 1000)})
        update: dict[str, Any] = {"$set": fields}
        if fields["status"] == "failed":
            update["$unset"] = {"dedupe_key": ""}
        try:
            await self._reports.update_one({"_id": reserved["_id"]}, update)
        except PyMongoError as exc:
            raise ReportPersistenceError(f"Could not record the report: {type(exc).__name__}") from exc

        stored = report_model.document_to_response({**{k: v for k, v in reserved.items() if k != "dedupe_key"}, **fields})
        logger.info("Report %s %s: assessment=%s", stored["report_id"], stored["status"], assessment_id)
        if stored["status"] == "failed":
            raise ReportGenerationFailedError(stored)
        return stored, False

    def _check_reportable(self, assessment: dict[str, Any]) -> None:
        status = assessment.get("status")
        if status != "completed":
            raise ReportPreconditionError(
                f"The assessment is {status}; a report needs a completed assessment."
                + (" A failed assessment is not reported as a successful one." if status == "failed" else "")
            )
        for name, label in (("correlation", "Correlation"), ("recommendation", "Recommendation generation")):
            if ((assessment.get(name) or {}).get("status")) == "running":
                raise ReportPreconditionError(f"{label} is running for this assessment; wait for it to finish.")

    def _snapshot(self, assessment: dict[str, Any], model: dict[str, Any], sources: TraceInputs) -> dict[str, Any]:
        corr = model["correlation"]
        return {
            "assessment_id": str(assessment["_id"]),
            "assessment_status": assessment.get("status"),
            "partial": bool(assessment.get("partial")),
            "qa_run_id": assessment.get("qa_run_id"),
            "security_run_id": assessment.get("security_run_id"),
            "evidence_count": len(sources.evidence),
            "ai_analysis_id": (model["ai"].get("analysis") or {}).get("analysis_id"),
            "ai_analysis_status": model["ai"]["status"],
            "correlation_status": corr["status"],
            "correlation_version": corr.get("correlation_version"),
            "priority_model_version": corr.get("priority_model_version"),
            "group_count": len(sources.groups),
            "issue_count": len(sources.issues),
            "recommendation_status": model["recommendations"]["status"],
            "recommendation_set": model["recommendations"]["ai_analysis_id"],
            "recommendation_count": len(model["recommendations"]["items"]),
            "retest_count": len(sources.retests),
        }

    def _render_and_write(self, assessment_id: str, report_id: str, model: dict[str, Any]) -> dict[str, Any]:
        html = render_html(model).encode("utf-8")
        pdf = render_pdf(model)
        if not pdf.startswith(b"%PDF-"):
            raise RuntimeError("PDF renderer returned no PDF")
        secrets = known_secrets(self._settings)
        leaks = sorted(set(find_leaks(html.decode("utf-8"), secrets) + find_leaks(pdf.decode("latin-1"), secrets)))
        if leaks:
            error = RuntimeError(f"The rendered report matched secret patterns ({', '.join(leaks)}); it was not stored.")
            error.category = "secret_leak"  # type: ignore[attr-defined]
            raise error

        folder = self._folder(assessment_id)
        folder.mkdir(parents=True, exist_ok=True)
        artifacts = {}
        for fmt, data in (("html", html), ("pdf", pdf)):
            filename = f"{report_id}.{fmt}"
            final = folder / filename
            temp = folder / f".{filename}.tmp"
            temp.write_bytes(data)
            os.replace(temp, final)
            artifacts[fmt] = {
                "format": fmt,
                "media_type": MEDIA_TYPES[fmt],
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "filename": filename,
                "path": final.relative_to(self._root()).as_posix(),
            }
        return {"status": "completed", "formats": ["html", "pdf"], "artifacts": artifacts, "error": None}

    # --- files -------------------------------------------------------------------------

    def _root(self) -> Path:
        return Path(self._settings.reports_root).resolve()

    def _folder(self, assessment_id: str) -> Path:
        # assessment_id is a validated 24-hex ObjectId string: no traversal possible.
        return self._root() / "assessments" / assessment_id

    async def artifact(self, assessment_id: str, report_id: str, fmt: str) -> tuple[bytes, str, str]:
        document = await self._report_document(assessment_id, report_id)
        artifact = (document.get("artifacts") or {}).get(fmt)
        if document.get("status") != "completed" or not artifact:
            raise ReportNotFoundError(f"{report_id} has no {fmt.upper()} file (status {document.get('status')}).")
        path = (self._root() / artifact["path"]).resolve()
        if self._root() not in path.parents:
            raise ReportArtifactIntegrityError(f"{report_id}: stored path is outside the reports folder.")
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ReportArtifactIntegrityError(f"{report_id}: the {fmt.upper()} file is missing ({type(exc).__name__}).") from exc
        if hashlib.sha256(data).hexdigest() != artifact.get("sha256"):
            raise ReportArtifactIntegrityError(f"{report_id}: the {fmt.upper()} file does not match its recorded SHA-256.")
        return data, MEDIA_TYPES[fmt], artifact["filename"]

    # --- loading (read-only) --------------------------------------------------------------

    async def _assessment(self, assessment_id: str) -> dict[str, Any]:
        if not ObjectId.is_valid(assessment_id):
            raise InvalidAssessmentIdError(f"{assessment_id!r} is not a valid assessment id.")
        assessment = await self._read(self._assessments, {"_id": ObjectId(assessment_id)})
        if assessment is None:
            raise AssessmentNotFoundError(f"No assessment with id {assessment_id}.")
        return assessment

    async def _load(self, assessment: dict[str, Any]) -> TraceInputs:
        aid = str(assessment["_id"])
        by = {"assessment_id": aid}
        tid, qid, sid = _oid(assessment.get("target_id")), _oid(assessment.get("qa_run_id")), _oid(assessment.get("security_run_id"))
        inputs = TraceInputs(
            assessment=assessment,
            target=await self._read(self._targets, {"_id": tid}) if tid else None,
            qa_run=await self._read(self._qa_runs, {"_id": qid}) if qid else None,
            security_run=await self._read(self._security_runs, {"_id": sid}) if sid else None,
            evidence=await self._all(self._evidence, by, evidence_model.LIST_SORT),
            analyses=await self._all(self._analyses, by, [("created_at", 1), ("_id", 1)], {"raw_response": 0}),
            groups=await self._all(self._groups, by, [("group_number", 1)]),
            issues=await self._all(self._issues, by, [("issue_number", 1)]),
            recommendations=await self._all(self._recommendations, by, [("recommendation_number", 1), ("_id", 1)]),
            retests=await self._all(self._retests, by, [("retest_number", 1)]),
        )
        own = {str(e["evidence_id"]) for e in inputs.evidence}
        unknown = sorted(referenced_evidence_ids(inputs) - own - {"None", ""})
        if unknown:
            found = await self._all(self._evidence, {"evidence_id": {"$in": unknown}}, None, {"evidence_id": 1, "assessment_id": 1})
            inputs.foreign_evidence = {str(d["evidence_id"]): str(d.get("assessment_id")) for d in found}
        run_ids = sorted({str(r) for t in inputs.retests for r in (t.get("source_run_ids") or [])})
        oids = [ObjectId(r) for r in run_ids if ObjectId.is_valid(r)]
        if oids:
            for collection in (self._qa_runs, self._security_runs):
                for doc in await self._all(collection, {"_id": {"$in": oids}}, None, {"target_id": 1}):
                    inputs.retest_runs[str(doc["_id"])] = str(doc.get("target_id"))
        return inputs

    async def _read(self, collection, query, sort=None, projection=None):
        try:
            return await collection.find_one(query, projection, sort=sort)
        except PyMongoError as exc:
            raise ReportPersistenceError(f"Could not read stored data: {type(exc).__name__}") from exc

    async def _read_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        return await self._read(self._reports, query, sort=report_model.LIST_SORT)

    async def _all(self, collection, query, sort=None, projection=None) -> list[dict[str, Any]]:
        try:
            cursor = collection.find(query, projection)
            if sort:
                cursor = cursor.sort(sort)
            return await cursor.to_list(length=None)
        except PyMongoError as exc:
            raise ReportPersistenceError(f"Could not read stored data: {type(exc).__name__}") from exc

    # --- numbering -----------------------------------------------------------------------

    async def _insert_numbered(self, document: dict[str, Any]) -> dict[str, Any]:
        for _ in range(_NUMBER_ATTEMPTS):
            last = await self._read(self._reports, {"assessment_id": document["assessment_id"]}, sort=report_model.LIST_SORT)
            number = int(last["report_number"]) + 1 if last else 1
            candidate = {**document, "report_id": report_reference(number), "report_number": number}
            try:
                result = await self._reports.insert_one(candidate)
            except DuplicateKeyError as exc:
                if report_model.DEDUPE_INDEX_NAME in str(exc):
                    raise
                continue  # another report took this number
            except PyMongoError as exc:
                raise ReportPersistenceError(f"Could not record the report: {type(exc).__name__}") from exc
            candidate["_id"] = result.inserted_id
            return candidate
        raise ReportPersistenceError("Could not allocate a report number.")

    async def _close_stale(self, assessment_id: str, now) -> None:
        stale_before = now - timedelta(seconds=self._settings.report_stale_seconds)
        try:
            await self._reports.update_many(
                {"assessment_id": assessment_id, "status": "running", "created_at": {"$lt": stale_before}},
                {"$set": {"status": "failed", "completed_at": now, "updated_at": now,
                          "error": {"category": "abandoned", "message": "The report never finished (the server may have stopped)."}},
                 "$unset": {"dedupe_key": ""}},
            )
        except PyMongoError as exc:
            raise ReportPersistenceError(f"Could not prepare the report: {type(exc).__name__}") from exc

    # --- reads ---------------------------------------------------------------------------

    async def list_reports(self, assessment_id: str, limit: int = DEFAULT_LIST_LIMIT) -> list[dict[str, Any]]:
        await self._assessment(assessment_id)
        documents = await self._all(self._reports, {"assessment_id": assessment_id}, report_model.LIST_SORT)
        return [report_model.document_to_response(d) for d in documents[:limit]]

    async def get(self, assessment_id: str, report_id: str) -> dict[str, Any]:
        return report_model.document_to_response(await self._report_document(assessment_id, report_id))

    async def _report_document(self, assessment_id: str, report_id: str) -> dict[str, Any]:
        await self._assessment(assessment_id)
        if not REPORT_ID_PATTERN.match(report_id):
            raise InvalidReportReferenceError(f"{report_id!r} is not a valid report reference (REPORT-###).")
        document = await self._read(self._reports, {"assessment_id": assessment_id, "report_id": report_id})
        if document is None:
            raise ReportNotFoundError(f"No report {report_id} for assessment {assessment_id}.")
        return document
