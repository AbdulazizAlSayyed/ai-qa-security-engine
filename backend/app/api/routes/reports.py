"""Report endpoints (Phase 10).

The only input is which assessment to report on. The server loads every
source record itself, audits traceability, and renders HTML + PDF from the
stored data. Nothing is re-run.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Query, Response, status
from fastapi.responses import JSONResponse

from app.api.dependencies import ReportServiceDep
from app.schemas.report import ReportRequest, ReportResponse
from app.services.report_service import DEFAULT_LIST_LIMIT

router = APIRouter(prefix="/assessments", tags=["reports"])

#: The HTML report is inert: no scripts, no remote loads, no framing.
_HTML_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


@router.post(
    "/{assessment_id}/reports",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assemble, audit and render a report of a completed assessment",
    responses={
        200: {"description": "Unchanged source data: the existing report is returned (reused=true)."},
        400: {"description": "Malformed assessment id."},
        404: {"description": "No such assessment."},
        409: {
            "description": "Assessment not completed (or correlation / recommendations running), a report for this "
            "data is being generated, or the traceability audit failed (recorded as a failed report)."
        },
        422: {"description": "A request body with fields was sent; this endpoint takes none."},
        500: {"description": "Rendering / leak audit / file write failed (recorded), or a persistence failure."},
    },
)
async def generate_report(
    assessment_id: str, service: ReportServiceDep, payload: ReportRequest | None = Body(default=None)
):
    report, reused = await service.generate(assessment_id)
    body = ReportResponse(**report, reused=reused)
    if reused:
        return JSONResponse(status_code=200, content=body.model_dump(mode="json"))
    return body


@router.get(
    "/{assessment_id}/reports",
    response_model=list[ReportResponse],
    summary="Reports of an assessment, newest first",
    responses={400: {"description": "Malformed id."}, 404: {"description": "No such assessment."}},
)
async def list_reports(
    assessment_id: str, service: ReportServiceDep, limit: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=500)
) -> list[ReportResponse]:
    return [ReportResponse(**item) for item in await service.list_reports(assessment_id, limit)]


@router.get(
    "/{assessment_id}/reports/{report_id}",
    response_model=ReportResponse,
    summary="One report's metadata",
    responses={400: {"description": "Malformed id or REPORT-###."}, 404: {"description": "No such assessment or report."}},
)
async def get_report(assessment_id: str, report_id: str, service: ReportServiceDep) -> ReportResponse:
    return ReportResponse(**await service.get(assessment_id, report_id))


@router.get(
    "/{assessment_id}/reports/{report_id}/html",
    summary="The rendered HTML report (self-contained)",
    response_class=Response,
    responses={200: {"content": {"text/html": {}}}, 404: {"description": "No such report or file."},
               500: {"description": "The stored file is missing or does not match its SHA-256."}},
)
async def report_html(assessment_id: str, report_id: str, service: ReportServiceDep) -> Response:
    data, media_type, filename = await service.artifact(assessment_id, report_id, "html")
    headers = {**_HTML_HEADERS, "Content-Disposition": f'inline; filename="{filename}"'}
    return Response(content=data, media_type=media_type, headers=headers)


@router.get(
    "/{assessment_id}/reports/{report_id}/pdf",
    summary="The rendered PDF report",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}, 404: {"description": "No such report or file."},
               500: {"description": "The stored file is missing or does not match its SHA-256."}},
)
async def report_pdf(assessment_id: str, report_id: str, service: ReportServiceDep) -> Response:
    data, media_type, filename = await service.artifact(assessment_id, report_id, "pdf")
    headers = {"Content-Disposition": f'attachment; filename="{filename}"', "X-Content-Type-Options": "nosniff"}
    return Response(content=data, media_type=media_type, headers=headers)
