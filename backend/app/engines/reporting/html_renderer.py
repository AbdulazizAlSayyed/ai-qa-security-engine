"""Deterministic, self-contained HTML for a report model.

No scripts, no remote CSS / fonts / images: one file that opens from disk,
prints, and converts to PDF. Every value is HTML-escaped. The same model
always renders to the same bytes.
"""

from __future__ import annotations

from html import escape
from typing import Any

SECTIONS = [
    ("summary", "Executive summary"),
    ("target", "Target information"),
    ("pipeline", "Assessment pipeline"),
    ("qa", "QA results"),
    ("security", "Security results"),
    ("evidence", "Evidence"),
    ("ai", "AI analysis"),
    ("issues", "Correlation and prioritized issues"),
    ("recommendations", "Recommendations"),
    ("retests", "Retests"),
    ("traceability", "Traceability audit"),
]

ADVISORY_STATEMENTS = [
    "Recommendations are advisory only.",
    "They are not confirmed vulnerabilities.",
    "They are not severity assignments and not priority assignments.",
    "None was applied automatically; no automatic source-code modification occurred.",
]

OUTCOME_TEXT = {
    "PASS": "PASS - the specified retest condition passed.",
    "FAIL": "FAIL - the specified condition was still failing.",
    "EXECUTION_FAILED": "Execution failed - the engine could not execute. No PASS/FAIL verdict.",
    "RUNNING": "Running - no verdict yet.",
    "NO_VERDICT": "No verdict.",
}

CSS = """
:root{--bg:#0b1220;--panel:#111a2b;--line:#23314a;--ink:#e2e8f0;--dim:#94a3b8;--accent:#38bdf8;
--pass:#34d399;--fail:#fb7185;--warn:#fbbf24;--adv:#c4b5fd}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.5 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:32px 0 8px;padding-top:8px;border-top:1px solid var(--line)}
h3{font-size:15px;margin:18px 0 6px}p,li{color:var(--ink)}.dim{color:var(--dim)}
code,.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;word-break:break-all}
table{width:100%;border-collapse:collapse;margin:8px 0;font-size:12.5px}
th,td{border:1px solid var(--line);padding:5px 7px;text-align:left;vertical-align:top}
td{overflow-wrap:anywhere}td:first-child{white-space:nowrap}
th{background:var(--panel);color:var(--dim);font-weight:600;white-space:nowrap}
.scroll{overflow-x:auto}.kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px}
.kv div{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:8px}
.kv b{display:block;font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.04em}
.box{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px;margin:10px 0}
.adv{border-color:#7c3aed;color:var(--adv)}.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-weight:600;font-size:12px}
.PASS{color:var(--pass)}.FAIL{color:var(--fail)}.EXECUTION_FAILED{color:var(--warn)}.RUNNING,.NO_VERDICT{color:var(--dim)}
nav a{color:var(--accent);margin-right:10px;font-size:12px}
@media print{:root{--bg:#fff;--panel:#f3f5f8;--line:#cbd5e1;--ink:#0f172a;--dim:#475569}nav{display:none}}
"""


def _e(value: Any) -> str:
    if value is None or value == "":
        return "&mdash;"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return escape(str(value), quote=True)


def _table(headers: list[str], rows: list[list[Any]], empty: str = "None.") -> str:
    if not rows:
        return f'<p class="dim">{_e(empty)}</p>'
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell if isinstance(cell, _Raw) else _e(cell)}</td>" for cell in row) + "</tr>" for row in rows)
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


class _Raw(str):
    """Already-escaped HTML fragment."""


def _join(values: list[Any] | None) -> str:
    return ", ".join(str(v) for v in values or []) or ""


def _kv(pairs: list[tuple[str, Any]]) -> str:
    return '<div class="kv">' + "".join(f"<div><b>{_e(k)}</b>{_e(v)}</div>" for k, v in pairs) + "</div>"


def render_html(model: dict[str, Any]) -> str:
    m = model["meta"]
    s = model["summary"]
    t = model["target"]
    p = model["pipeline"]
    out: list[str] = []
    w = out.append
    w("<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">")
    w('<meta name="viewport" content="width=device-width, initial-scale=1">')
    w(f"<title>{_e(m.get('report_id'))} - Assessment report</title><style>{CSS}</style></head><body><main>")
    w(f"<h1>Assessment report {_e(m.get('report_id'))}</h1>")
    w(f'<p class="dim">Target <b>{_e(t["name"])}</b> &middot; assessment <code>{_e(m["assessment_id"])}</code> '
      f"&middot; generated {_e(m.get('generated_at'))} &middot; report contract v{_e(m['report_version'])} "
      f"&middot; source fingerprint <code>{_e((m.get('source_fingerprint') or '')[:16])}</code></p>")
    w('<p class="dim">Assembled only from stored records. Nothing was re-run to produce this report: no scan, '
      "no browser, no AI call, no correlation, no recommendation generation, no retest.</p>")
    w("<nav>" + "".join(f'<a href="#{sid}">{_e(title)}</a>' for sid, title in SECTIONS) + "</nav>")

    # 1 executive summary
    w('<h2 id="summary">Executive summary</h2>')
    qa, sec, r = s.get("qa") or {}, s.get("security") or {}, s["retests"]
    w(_kv([
        ("Assessment status", s["assessment_status"]),
        ("Partial", s["partial"]),
        ("QA checks", f"{qa.get('total', 0)} total / {qa.get('passed', 0)} passed / {qa.get('failed', 0)} failed / "
                      f"{qa.get('skipped', 0)} skipped / {qa.get('error', 0)} error"),
        ("Security findings (tool severity)", f"{sec.get('total', 0)} total / {sec.get('high', 0)} high / {sec.get('medium', 0)} medium / "
                                              f"{sec.get('low', 0)} low / {sec.get('informational', 0)} informational"),
        ("Evidence records", s["evidence_total"]),
        ("Prioritized issues", s["issue_total"]),
        ("Priority distribution", " / ".join(f"{k} {v}" for k, v in s["priority_counts"].items())),
        ("AI analysis", s["ai_analysis_status"]),
        ("Correlation", s["correlation_status"]),
        ("Recommendations", f"{s['recommendation_status']} ({s['recommendation_count']})"),
        ("Retests", f"{r['total']} total / {r['passed']} PASS / {r['failed']} FAIL / {r['execution_failed']} execution failed"),
        ("Traceability", model["traceability"]["status"]),
    ]))
    if s["partial"]:
        w('<div class="box FAIL">PARTIAL ASSESSMENT: one engine stage could not execute. See the pipeline section for the stored reason.</div>')
    w('<p class="dim">Tool severity is the scanner\'s own rating. Priority (P1-P4) is the platform\'s derived ranking. '
      "AI confidence is how sure the model was. They are separate and never converted into each other.</p>")

    # 2 target
    w('<h2 id="target">Target information</h2>')
    w(_kv([("Target id", t["target_id"]), ("Name", t["name"]), ("Base URL", t["base_url"]), ("API URL", t["api_url"]),
           ("Type", t["type"]), ("Source", t["source"])]))
    if t.get("registered") is None:
        w('<p class="dim">The target is no longer in the registry; the assessment snapshot above is used.</p>')
    elif t.get("registry_differs"):
        reg = t["registered"]
        w(f'<p class="dim">The registry entry has changed since this assessment (now {_e(reg["name"])} / {_e(reg["base_url"])}). '
          "This report shows the snapshot taken by the assessment.</p>")

    # 3 pipeline
    w('<h2 id="pipeline">Assessment pipeline</h2>')
    w(_kv([("Status", p["status"]), ("Partial", p["partial"]), ("Created", p["created_at"]), ("Started", p["started_at"]),
           ("Finished", p["finished_at"]), ("Duration (ms)", p["duration_ms"]), ("Error", p["error"])]))
    w("<h3>Stages</h3>")
    w(_table(["Stage", "Stage status", "Run id", "Run verdict", "Stored reason"],
             [[x["stage"], x["status"], x["run_id"], x["run_status"], x["error"]] for x in p["stages"]]))
    w("<h3>State history</h3>")
    w(_table(["State", "Timestamp (UTC)", "Message"], [[x["state"], x["timestamp"], x["message"]] for x in p["state_history"]]))

    # 4 QA
    q = model["qa"]
    w('<h2 id="qa">QA results</h2>')
    w(f'<p class="dim">From the persisted QA run <code>{_e(q["run_id"])}</code> (run verdict {_e(q["run_status"])}, '
      f"stage {_e(q['stage_status'])}). Playwright was not re-run.</p>")
    w(_table(["Ref", "Check", "Status", "Expected", "Actual", "Error", "Component"],
             [[x["ref"], x["title"], x["status"], x["expected"], x["actual"], x["error"], x["target_component"]] for x in q["checks"]],
             "No QA checks were recorded."))
    w("<h3>Console errors observed</h3>")
    w(_table(["Ref", "Title", "Status", "Actual", "Location"],
             [[x["ref"], x["title"], x["status"], x["actual"], x["target_component"]] for x in q["console_errors"]]))
    w("<h3>Network failures observed</h3>")
    w(_table(["Ref", "Title", "Status", "Actual", "Request"],
             [[x["ref"], x["title"], x["status"], x["actual"], x["target_component"]] for x in q["network_failures"]]))

    # 5 security
    sc = model["security"]
    w('<h2 id="security">Security results</h2>')
    w(f'<p class="dim">From the persisted security run <code>{_e(sc["run_id"])}</code> (run verdict {_e(sc["run_status"])}, '
      f"stage {_e(sc['stage_status'])}). No scanner was re-run. Severity below is the tool's own severity, not a priority.</p>")
    w("<h3>Scanner coverage</h3>")
    w(_table(["Source", "Status", "Detail"], [[x["source"], x["status"], x["detail"]] for x in sc["coverage"]]))
    w("<h3>Components</h3>")
    w(_table(["Component", "Enabled", "Status", "Findings", "Detail / skip reason"],
             [[x["name"], x["enabled"], x["status"], x["finding_count"], x["detail"]] for x in sc["components"]]))
    w("<h3>Findings</h3>")
    w(_table(["Ref", "Source", "Category", "Title", "Component", "Status", "Tool severity"],
             [[x["ref"], x["source"], x["category"], x["title"], x["target_component"], x["status"], x["tool_severity"]] for x in sc["findings"]]))

    # 6 evidence
    w('<h2 id="evidence">Evidence</h2>')
    w('<p class="dim">Every normalized record, with the raw run and finding it came from. Raw scanner payloads are not included.</p>')
    w(_table(["Ref", "Evidence id", "Source", "Type", "Category", "Title", "Component", "Status", "Expected", "Actual", "Source run", "Source finding"],
             [[x["ref"], _Raw(f'<span class="mono">{_e(x["evidence_id"])}</span>'), x["source"], x["finding_type"], x["category"], x["title"],
               x["target_component"], x["status"], x["expected"], x["actual"], _Raw(f'<span class="mono">{_e(x["source_run_id"])}</span>'),
               x["source_finding_id"]] for x in model["evidence"]], "No evidence was recorded."))

    # 7 AI
    ai = model["ai"]
    w('<h2 id="ai">AI analysis</h2>')
    w(f'<p class="dim">Assessment AI status: {_e(ai["status"])} &middot; {_e(ai["attempts"])} attempt(s), '
      f"{_e(ai['failed_attempts'])} failed. The model was not called for this report.</p>")
    if ai.get("latest_failure"):
        f = ai["latest_failure"]
        w(f'<div class="box">Latest attempt failed ({_e(f["provider"])} / {_e(f["model"])}, {_e(f["at"])}): '
          f"<b>{_e(f['category'])}</b> &mdash; {_e(f['message'])}</div>")
    a = ai.get("analysis")
    if a is None:
        w('<p>No completed AI analysis exists for this assessment. No AI findings are shown.</p>')
    else:
        w(_kv([("Analysis id", a["analysis_id"]), ("Provider", a["provider"]), ("Model", a["model"]),
               ("Contract version", a["analysis_version"]), ("Status", a["status"]), ("Completed", a["completed_at"])]))
        w(f'<div class="box"><b>Overall assessment</b><br>{_e(a["overall_assessment"])}</div>')
        w(_table(["Finding", "Type", "Status", "Title", "AI confidence", "Tool severity", "Cited evidence", "Uncertainty"],
                 [[x["finding_id"], x["type"], x["status"], x["title"], x["confidence"], x["tool_severity"], _join(x["evidence_refs"]),
                   x["uncertainty"]] for x in a["findings"]], "The analysis reported no findings."))
        w("<h3>Evidence gaps</h3>" + _list(a["evidence_gaps"]))
        w("<h3>Limitations</h3>" + _list(a["limitations"]))

    # 8 issues
    c = model["correlation"]
    w('<h2 id="issues">Correlation and prioritized issues</h2>')
    w(f'<p class="dim">Correlation status {_e(c["status"])} &middot; correlation v{_e(c["correlation_version"])} &middot; '
      f"priority model v{_e(c['priority_model_version'])} &middot; completed {_e(c['completed_at'])}. "
      "Priorities, scores and factors are the stored Phase 6 values; nothing was recalculated.</p>")
    w(_table(["Group", "Rule", "Reason", "Type", "Tool severity", "Evidence"],
             [[g["correlation_group_id"], g["correlation_rule"], g["correlation_reason"], g["finding_type"], g["tool_severity"],
               _join(g["evidence_refs"])] for g in c["groups"]], "No correlation groups."))
    for i in c["issues"]:
        factors = "; ".join(f"{f['factor']} {f['points']:+d} ({f['detail']})" for f in i["score_factors"])
        w(f'<div class="box"><b>{_e(i["issue_id"])}</b> &middot; priority <b>{_e(i["priority"])}</b> (score {_e(i["priority_score"])}) '
          f"&middot; {_e(i['type'])} &middot; tool severity {_e(i['tool_severity'])} &middot; AI confidence {_e(i['ai_confidence'])}<br>"
          f"{_e(i['title'])}<br><span class=\"dim\">Group {_e(i['correlation_group_id'])} &middot; rule {_e(i['correlation_rule'])} &middot; "
          f"{_e(i['correlation_reason'])}</span><br>Score factors: {_e(factors)}<br>Reasons: {_e(_join(i['priority_reasons']))}<br>"
          f"Components: <span class=\"mono\">{_e(_join(i['affected_components']))}</span><br>Evidence: {_e(_join(i['evidence_refs']))}"
          f"<br>AI support: {_e(_join(i['ai_finding_ids']) or 'none')}</div>")
    if not c["issues"]:
        w('<p class="dim">No prioritized issues.</p>')

    # 9 recommendations
    rc = model["recommendations"]
    w('<h2 id="recommendations">Recommendations</h2>')
    w('<div class="box adv"><b>ADVISORY ONLY</b><ul>' + "".join(f"<li>{_e(x)}</li>" for x in ADVISORY_STATEMENTS) + "</ul></div>")
    w(f'<p class="dim">Generation status {_e(rc["status"])} &middot; set from AI analysis {_e(rc["ai_analysis_id"])} '
      f"&middot; {_e(rc['set_count'])} set(s) stored.</p>")
    for x in rc["items"]:
        spec = x.get("retest") or {}
        w(f'<div class="box"><b>{_e(x["recommendation_id"])}</b> &middot; <span class="pill adv">ADVISORY</span> &middot; for {_e(x["issue_id"])}'
          f" &middot; {_e(x['type'])} &middot; AI confidence {_e(x['confidence'])}<br><b>{_e(x['title'])}</b><br>{_e(x['description'])}"
          f"<br><span class=\"dim\">Why: {_e(x['rationale'])}</span><br>Evidence: {_e(_join(x['evidence_refs']))}"
          f"<br><span class=\"dim\">Retest specification: {_e(spec.get('retest_type'))} / {_e(spec.get('scope'))} on "
          f"<span class=\"mono\">{_e(spec.get('target_component'))}</span>; passes when {_e(spec.get('pass_condition'))}; "
          f"checks {_e(_join(spec.get('checks')))}</span></div>")
    if not rc["items"]:
        w('<p class="dim">No recommendations have been generated.</p>')

    # 10 retests
    w('<h2 id="retests">Retests</h2>')
    w("<ul>" + "".join(f'<li class="{k}">{_e(v)}</li>' for k, v in OUTCOME_TEXT.items() if k in ("PASS", "FAIL", "EXECUTION_FAILED")) + "</ul>")
    w(_table(["Retest", "Rec", "Issue", "Type / scope", "Outcome", "Status", "Verdict", "Started", "Completed", "Plan", "Source runs",
              "Evidence seen again", "Result", "Error"],
             [[x["retest_id"], x["recommendation_id"], x["issue_id"], f"{x['type']} / {x['scope']}",
               _Raw(f'<b class="{_e(x["outcome"])}">{_e(x["outcome"].replace("_", " "))}</b>'), x["status"], x["verdict"],
               x["started_at"], x["completed_at"],
               f"{x['plan']['engine']}: {_join(x['plan']['components'] or x['plan']['qa_checks'])}", _join(x["source_runs"]),
               _join(x["matched_evidence_refs"]), x["result_summary"], x["error"]] for x in model["retests"]],
             "No retests have been run."))
    for x in model["retests"]:
        if x["observations"] or x["checks"]:
            w(f'<p class="dim">{_e(x["retest_id"])} checks: {_e(_join(x["checks"]))}. Observations: {_e(" / ".join(x["observations"]) or "none")}.</p>')

    # 11 traceability
    tr = model["traceability"]
    w('<h2 id="traceability">Traceability audit</h2>')
    w(f'<p>Status: <b class="{"PASS" if tr["status"] == "passed" else "FAIL"}">{_e(tr["status"])}</b> &middot; '
      f"{_e(tr['links_checked'])} stored references checked.</p>")
    w('<p class="dim">Chain: target &rarr; assessment &rarr; raw QA / security run &rarr; evidence &rarr; AI analysis &rarr; '
      "correlation group &rarr; issue &rarr; recommendation &rarr; retest &rarr; report.</p>")
    w(_table(["Relationship", "References checked"], [[k, v] for k, v in tr["checks"].items()]))
    w(_table(["Relationship", "Source", "Reference", "Problem"],
             [[e["relationship"], e["source"], e["reference"], e["problem"]] for e in tr["errors"]], "No broken references."))
    w("</main></body></html>\n")
    return "".join(out)


def _list(values: list[str]) -> str:
    if not values:
        return '<p class="dim">None.</p>'
    return "<ul>" + "".join(f"<li>{_e(v)}</li>" for v in values) + "</ul>"
