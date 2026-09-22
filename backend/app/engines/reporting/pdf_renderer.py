"""PDF rendering of a report model with ReportLab (pure Python, no browser).

Same sections and the same factual content as the HTML; the layout is
simpler (tables with fewer columns). ``invariant=1`` removes the creation
timestamp / random id from the file, so one model renders to the same
bytes, and page compression is off so the text stays searchable in tests.
Standard PDF fonts only cover cp1252, so other characters render as "?".
"""

from __future__ import annotations

from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.engines.reporting.html_renderer import ADVISORY_STATEMENTS, OUTCOME_TEXT, SECTIONS

_styles = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=_styles["Heading1"], fontSize=16, spaceAfter=4)
H2 = ParagraphStyle("h2", parent=_styles["Heading2"], fontSize=13, spaceBefore=10, spaceAfter=4)
H3 = ParagraphStyle("h3", parent=_styles["Heading3"], fontSize=10.5, spaceBefore=6, spaceAfter=2)
BODY = ParagraphStyle("body", parent=_styles["BodyText"], fontSize=8.5, leading=10.5)
DIM = ParagraphStyle("dim", parent=BODY, textColor=colors.HexColor("#475569"))
CELL = ParagraphStyle("cell", parent=BODY, fontSize=7, leading=8.5)


def _t(value: Any) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, bool):
        value = "yes" if value else "no"
    text = str(value).encode("cp1252", "replace").decode("cp1252")
    return escape(text)


def _j(values: list[Any] | None) -> str:
    return ", ".join(str(v) for v in values or [])


def _p(text: str, style: ParagraphStyle = BODY) -> Paragraph:
    return Paragraph(text, style)


def _table(headers: list[str], rows: list[list[Any]], widths: list[float], empty: str = "None.") -> list:
    if not rows:
        return [_p(_t(empty), DIM)]
    data = [[_p(f"<b>{_t(h)}</b>", CELL) for h in headers]]
    data += [[_p(_t(c), CELL) for c in row] for row in rows]
    total = sum(widths)
    usable = landscape(A4)[0] - 24 * mm
    table = Table(data, colWidths=[usable * w / total for w in widths], repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return [table, Spacer(1, 4)]


def _kv(pairs: list[tuple[str, Any]]) -> list:
    return _table(["Field", "Value"], [[k, v] for k, v in pairs], [1, 3])


def render_pdf(model: dict[str, Any]) -> bytes:
    m, s, t, p = model["meta"], model["summary"], model["target"], model["pipeline"]
    story: list = []
    add = story.extend
    titles = dict(SECTIONS)

    story.append(_p(f"Assessment report {_t(m.get('report_id'))}", H1))
    story.append(_p(f"Target {_t(t['name'])} - assessment {_t(m['assessment_id'])} - generated {_t(m.get('generated_at'))} - "
                    f"report contract v{_t(m['report_version'])} - source fingerprint {_t((m.get('source_fingerprint') or '')[:16])}", DIM))
    story.append(_p("Assembled only from stored records. Nothing was re-run to produce this report: no scan, no browser, "
                    "no AI call, no correlation, no recommendation generation, no retest.", DIM))

    qa, sec, r = s.get("qa") or {}, s.get("security") or {}, s["retests"]
    story.append(_p(titles["summary"], H2))
    add(_kv([
        ("Assessment status", s["assessment_status"]), ("Partial", s["partial"]),
        ("QA checks", f"{qa.get('total', 0)} total / {qa.get('passed', 0)} passed / {qa.get('failed', 0)} failed / "
                      f"{qa.get('skipped', 0)} skipped / {qa.get('error', 0)} error"),
        ("Security findings (tool severity)", f"{sec.get('total', 0)} total / {sec.get('high', 0)} high / {sec.get('medium', 0)} medium / "
                                              f"{sec.get('low', 0)} low / {sec.get('informational', 0)} informational"),
        ("Evidence records", s["evidence_total"]), ("Prioritized issues", s["issue_total"]),
        ("Priority distribution", " / ".join(f"{k} {v}" for k, v in s["priority_counts"].items())),
        ("AI analysis", s["ai_analysis_status"]), ("Correlation", s["correlation_status"]),
        ("Recommendations", f"{s['recommendation_status']} ({s['recommendation_count']})"),
        ("Retests", f"{r['total']} total / {r['passed']} PASS / {r['failed']} FAIL / {r['execution_failed']} execution failed"),
        ("Traceability", model["traceability"]["status"]),
    ]))
    if s["partial"]:
        story.append(_p("<b>PARTIAL ASSESSMENT:</b> one engine stage could not execute. See the pipeline section.", BODY))
    story.append(_p("Tool severity, priority (P1-P4) and AI confidence are separate concepts and are never converted into each other.", DIM))

    story.append(_p(titles["target"], H2))
    add(_kv([("Target id", t["target_id"]), ("Name", t["name"]), ("Base URL", t["base_url"]), ("API URL", t["api_url"]),
             ("Type", t["type"]), ("Source", t["source"])]))
    if t.get("registry_differs"):
        story.append(_p("The registry entry has changed since this assessment; the assessment snapshot is shown.", DIM))

    story.append(_p(titles["pipeline"], H2))
    add(_kv([("Status", p["status"]), ("Partial", p["partial"]), ("Created", p["created_at"]), ("Started", p["started_at"]),
             ("Finished", p["finished_at"]), ("Duration (ms)", p["duration_ms"]), ("Error", p["error"])]))
    add(_table(["Stage", "Stage status", "Run id", "Run verdict", "Stored reason"],
               [[x["stage"], x["status"], x["run_id"], x["run_status"], x["error"]] for x in p["stages"]], [1, 1, 2, 1, 3]))
    add(_table(["State", "Timestamp (UTC)", "Message"], [[x["state"], x["timestamp"], x["message"]] for x in p["state_history"]], [1, 1, 3]))

    q = model["qa"]
    story.append(_p(titles["qa"], H2))
    story.append(_p(f"Persisted QA run {_t(q['run_id'])} (run verdict {_t(q['run_status'])}). Playwright was not re-run.", DIM))
    add(_table(["Ref", "Check", "Status", "Expected", "Actual", "Error"],
               [[x["ref"], x["title"], x["status"], x["expected"], x["actual"], x["error"]] for x in q["checks"]], [0.7, 2, 0.8, 2, 2, 2],
               "No QA checks were recorded."))
    story.append(_p("Console errors observed", H3))
    add(_table(["Ref", "Title", "Status", "Actual", "Location"],
               [[x["ref"], x["title"], x["status"], x["actual"], x["target_component"]] for x in q["console_errors"]], [0.7, 2, 0.8, 3, 2]))
    story.append(_p("Network failures observed", H3))
    add(_table(["Ref", "Title", "Status", "Actual", "Request"],
               [[x["ref"], x["title"], x["status"], x["actual"], x["target_component"]] for x in q["network_failures"]], [0.7, 2, 0.8, 3, 2]))

    sc = model["security"]
    story.append(_p(titles["security"], H2))
    story.append(_p(f"Persisted security run {_t(sc['run_id'])} (run verdict {_t(sc['run_status'])}). No scanner was re-run. "
                    "Severity is the tool's own severity, not a priority.", DIM))
    add(_table(["Source", "Status", "Detail"], [[x["source"], x["status"], x["detail"]] for x in sc["coverage"]], [1, 1, 4]))
    add(_table(["Component", "Enabled", "Status", "Findings", "Detail / skip reason"],
               [[x["name"], x["enabled"], x["status"], x["finding_count"], x["detail"]] for x in sc["components"]], [1, 0.7, 1, 0.7, 4]))
    add(_table(["Ref", "Source", "Category", "Title", "Component", "Status", "Tool severity"],
               [[x["ref"], x["source"], x["category"], x["title"], x["target_component"], x["status"], x["tool_severity"]]
                for x in sc["findings"]], [0.7, 0.8, 1, 2.5, 2.5, 0.8, 0.9]))

    story.append(_p(titles["evidence"], H2))
    story.append(_p("Every normalized record with its source run and source finding. Raw scanner payloads are not included.", DIM))
    add(_table(["Ref", "Evidence id", "Source", "Type", "Title", "Component", "Status", "Expected / actual", "Source run / finding"],
               [[x["ref"], x["evidence_id"], x["source"], x["finding_type"], x["title"], x["target_component"], x["status"],
                 f"{x['expected'] or '-'} / {x['actual'] or '-'}", f"{x['source_run_id']} / {x['source_finding_id']}"]
                for x in model["evidence"]], [0.6, 1.6, 0.7, 0.5, 1.8, 1.8, 0.7, 2, 1.7], "No evidence was recorded."))

    ai = model["ai"]
    story.append(_p(titles["ai"], H2))
    story.append(_p(f"Assessment AI status {_t(ai['status'])} - {_t(ai['attempts'])} attempt(s), {_t(ai['failed_attempts'])} failed. "
                    "The model was not called for this report.", DIM))
    if ai.get("latest_failure"):
        f = ai["latest_failure"]
        story.append(_p(f"Latest attempt failed ({_t(f['provider'])} / {_t(f['model'])}): <b>{_t(f['category'])}</b> - {_t(f['message'])}"))
    a = ai.get("analysis")
    if a is None:
        story.append(_p("No completed AI analysis exists for this assessment. No AI findings are shown."))
    else:
        add(_kv([("Analysis id", a["analysis_id"]), ("Provider", a["provider"]), ("Model", a["model"]),
                 ("Contract version", a["analysis_version"]), ("Status", a["status"]), ("Overall assessment", a["overall_assessment"])]))
        add(_table(["Finding", "Type", "Status", "Title", "AI confidence", "Tool severity", "Cited evidence", "Uncertainty"],
                   [[x["finding_id"], x["type"], x["status"], x["title"], x["confidence"], x["tool_severity"], _j(x["evidence_refs"]),
                     x["uncertainty"]] for x in a["findings"]], [0.8, 0.6, 1, 2, 0.8, 0.8, 1.2, 2.5], "The analysis reported no findings."))
        add(_table(["Evidence gaps"], [[x] for x in a["evidence_gaps"]], [1]))
        add(_table(["Limitations"], [[x] for x in a["limitations"]], [1]))

    c = model["correlation"]
    story.append(_p(titles["issues"], H2))
    story.append(_p(f"Correlation {_t(c['status'])} - correlation v{_t(c['correlation_version'])} - priority model "
                    f"v{_t(c['priority_model_version'])}. Stored Phase 6 values; nothing was recalculated.", DIM))
    add(_table(["Group", "Rule", "Reason", "Tool severity", "Evidence"],
               [[g["correlation_group_id"], g["correlation_rule"], g["correlation_reason"], g["tool_severity"], _j(g["evidence_refs"])]
                for g in c["groups"]], [0.8, 1.2, 3, 0.8, 1.5], "No correlation groups."))
    add(_table(["Issue", "Priority", "Score", "Score factors", "Reasons", "Tool severity", "AI confidence", "Components", "Evidence", "AI support"],
               [[i["issue_id"], i["priority"], i["priority_score"],
                 "; ".join(f"{f['factor']} {f['points']:+d}" for f in i["score_factors"]), _j(i["priority_reasons"]),
                 i["tool_severity"], i["ai_confidence"], _j(i["affected_components"]), _j(i["evidence_refs"]), _j(i["ai_finding_ids"]) or "none"]
                for i in c["issues"]], [0.8, 0.6, 0.5, 1.6, 2, 0.8, 0.8, 2, 1, 0.8], "No prioritized issues."))

    rc = model["recommendations"]
    story.append(_p(titles["recommendations"], H2))
    story.append(_p("<b>ADVISORY ONLY.</b> " + " ".join(_t(x) for x in ADVISORY_STATEMENTS)))
    add(_table(["Rec", "Issue", "Type", "AI confidence", "Recommendation", "Evidence", "Retest specification"],
               [[x["recommendation_id"], x["issue_id"], x["type"], x["confidence"], f"[ADVISORY] {x['title']}: {x['description']}",
                 _j(x["evidence_refs"]),
                 f"{(x.get('retest') or {}).get('retest_type')} / {(x.get('retest') or {}).get('scope')}; passes when "
                 f"{(x.get('retest') or {}).get('pass_condition')}; checks {_j((x.get('retest') or {}).get('checks'))}"]
                for x in rc["items"]], [0.6, 0.7, 1, 0.7, 4, 1, 2.5], "No recommendations have been generated."))

    story.append(_p(titles["retests"], H2))
    for key in ("PASS", "FAIL", "EXECUTION_FAILED"):
        story.append(_p(_t(OUTCOME_TEXT[key]), DIM))
    add(_table(["Retest", "Rec", "Issue", "Outcome", "Status", "Verdict", "Started / completed", "Plan", "Source runs", "Seen again", "Result / error"],
               [[x["retest_id"], x["recommendation_id"], x["issue_id"], x["outcome"].replace("_", " "), x["status"], x["verdict"],
                 f"{x['started_at']} / {x['completed_at']}", f"{x['plan']['engine']}: {_j(x['plan']['components'] or x['plan']['qa_checks'])}",
                 _j(x["source_runs"]), _j(x["matched_evidence_refs"]), x["result_summary"] or x["error"]]
                for x in model["retests"]], [0.8, 0.6, 0.7, 0.9, 0.7, 0.6, 1.5, 1.3, 1.5, 0.8, 2], "No retests have been run."))

    tr = model["traceability"]
    story.append(_p(titles["traceability"], H2))
    story.append(_p(f"Status: <b>{_t(tr['status'])}</b> - {_t(tr['links_checked'])} stored references checked. Chain: target - assessment - "
                    "raw QA / security run - evidence - AI analysis - correlation group - issue - recommendation - retest - report."))
    add(_table(["Relationship", "References checked"], [[k, v] for k, v in tr["checks"].items()], [3, 1]))
    add(_table(["Relationship", "Source", "Reference", "Problem"],
               [[e["relationship"], e["source"], e["reference"], e["problem"]] for e in tr["errors"]], [1.5, 1, 1.5, 3], "No broken references."))

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
        title=f"Assessment report {m.get('report_id')}", author="AI QA Security Engine", subject=str(m["assessment_id"]),
        invariant=1, pageCompression=0,
    )
    doc.build(story)
    return buffer.getvalue()
