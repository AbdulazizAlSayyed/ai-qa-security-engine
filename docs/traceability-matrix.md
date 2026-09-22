# AI QA Security Engine — Requirements Traceability Matrix (FR-0 … FR-10)

Updated 2026-09-22 (Phase 10). Paths are relative to `backend/app/` or `frontend/src/`; tests to `backend/tests/`.

## Verification status legend

| Label | Meaning |
|---|---|
| **Implemented** | The code exists and is wired end to end. |
| **Focused-tested** | Automated tests pass, against real MongoDB where noted, with **FAKE** engines or provider where noted. |
| **Verified in phase** | A real run was performed during that phase: real target, real engine. |
| **Deferred final verification** | Part of the single final pass, which has not been performed yet. |
| **Blocked real-model** | A real OpenAI run has not succeeded. The configured key returns `401 invalid_api_key`. |

A fake provider is **not** a real OpenAI verification, and a fake engine is **not** a real retest.

## Matrix

| FR | Requirement | Phase | Backend implementation | API | Frontend | MongoDB | Tests | Verification status |
|---|---|---|---|---|---|---|---|---|
| FR-0 | Scaffolding, config, DB wiring, health | 0 | `main.py`, `core/config.py`, `core/database.py` (PyMongo `AsyncMongoClient`) | `GET /health`, `GET /health/live`, `GET /` | `DashboardPage` (health chain), `ConnectionChain` | — | `test_health`, `test_config`, `test_database` | Implemented · verified in phase · deferred final verification |
| FR-1 | Target registry | 1 | `services/target_service.py`, `models/target.py` | `POST/GET/PATCH/DELETE /targets` | `TargetsPage`, `targets/*` | `targets` | `test_targets` | Implemented · verified in phase (Mini E-Commerce registered, id `6aa9dc1a…9073`) · deferred final verification |
| FR-2 | QA engine (Playwright smoke suite) | 2 | `engines/qa/*`, `services/qa_service.py` | `POST/GET /qa/runs` | `QaPage`, `qa/*` | `qa_runs` | `test_qa_engine`, `test_qa_api` | Implemented · verified in phase against Mini E-Commerce · **limitation:** the Mini E-Commerce known-defect suite does not exist (`test-targets/mini-ecommerce` holds only `.gitkeep`) · deferred final verification |
| FR-3 | Security engine: ZAP baseline, API probes, Semgrep; no active scan | 3 | `engines/security/*`, `services/security_service.py` | `POST/GET /security/runs` | `SecurityPage`, `security/*` | `security_runs` | `test_security_engine`, `test_security_api` | Implemented · verified in phase (real ZAP 2.17) · authorization probes skip without registered credentials · deferred final verification |
| FR-4 | Assessment orchestration, state machine, normalization, partial semantics | 4 | `engines/orchestrator/*`, `services/assessment_service.py` | `POST/GET /assessments`, `GET /assessments/{id}/evidence` | `AssessmentsPage`, `AssessmentDetailPage`, `EvidenceTable` | `assessments`, `evidence` | `test_orchestrator`, `test_assessments_api` | Implemented · verified in phase (real run 2026-09-21) · deferred final verification |
| FR-5 | Evidence-grounded AI analysis (`AIProvider` → `OpenAIProvider`) | 5 | `engines/ai/*`, `services/ai_analysis_service.py` | `POST/GET /assessments/{id}/ai-analysis`, `…/history` | `AIAnalysisPanel` | `ai_analysis_logs` | `test_ai_analysis`, `test_ai_analysis_api`, `test_ai_provider` (FAKE provider) | Implemented · focused-tested (FAKE provider) · **blocked real-model** (2 real attempts, both `authentication` / 401) |
| FR-6 | Correlation and deterministic prioritization | 6 | `engines/correlation/*`, `engines/prioritization/*`, `services/correlation_service.py`, `services/issue_service.py` | `POST /assessments/{id}/correlation`, `GET …/correlation-groups`, `GET …/issues[/{ISSUE}]` | `IssuesPanel`, `IssueDetails`, `PriorityBadge` | `correlation_groups`, `issues` | `test_correlation`, `test_correlation_api` | Implemented · focused-tested (AI input from FAKE provider) · deferred final verification |
| FR-7 | Dashboard aggregation, history, trends, drill-down | 7 | `services/dashboard_service.py` (read-only aggregation, no collection) | `GET /dashboard` | `DashboardPage`, `dashboard/*` | reads `assessments`, `issues`, `targets` | `test_dashboard` | Implemented · focused-tested (incl. a Playwright UI check with the TEMP harness) · deferred final verification |
| FR-8 | Advisory recommendations with a retest specification | 8 | `engines/remediation/*`, `services/recommendation_service.py` | `POST/GET /assessments/{id}/recommendations[/{REC}]` | `RecommendationsPanel` | `recommendations` | `test_recommendations`, `test_recommendations_api` (FAKE provider) | Implemented · focused-tested (FAKE provider) · **blocked real-model** · deferred final verification |
| FR-9 | Retest: scoped re-run, deterministic PASS / FAIL, status ≠ verdict | 9 | `engines/retest/*`, `services/retest_service.py`, scoped `QaService` / `SecurityService` | `POST …/recommendations/{REC}/retest`, `GET …/retests[/{RETEST}]` | `RetestsPanel`, Run Retest on the recommendation cards | `retests` (plus scoped raw runs in `qa_runs` / `security_runs`) | `test_retests`, `test_retests_api` (FAKE engines) | Implemented · focused-tested (FAKE engines, plus a Playwright UI check) · **no real QA or security retest against Mini E-Commerce yet** · deferred final verification |
| FR-10 | Reports: traceability audit, assembly, HTML + PDF, persistence | 10 | `engines/reporting/*` (traceability, assembler, redaction, html_renderer, pdf_renderer), `services/report_service.py`, `scripts/final_verification.py` | `POST/GET /assessments/{id}/reports`, `GET …/reports/{REPORT}`, `…/html`, `…/pdf` | `ReportsPanel` | `reports` (+ files under `REPORTS_ROOT`) | `test_reports`, `test_reports_api`, `test_frontend_contract` | Implemented · focused-tested (real audit, rendering and persistence over FAKE-sourced data; Playwright UI check 13/13) · the real-DB traceability audit of the 3 stored assessments passed · no report has been generated from real data yet · deferred final verification |

## Final verification checklist

`backend/scripts/final_verification.py` is read-only. It reports each item as PASS, FAIL, EVIDENCE FOUND, NOT VERIFIED or MANUAL. Records from fake engines or providers never count.

| # | Item | How | Status on 2026-09-22 |
|---|---|---|---|
| 1 | Full pytest regression | manual run | 614 passed during Phase 10; the final run is still due |
| 2 | Real end-to-end assessment | DB evidence + manual confirmation | Evidence found (3 completed; real QA and security runs) — confirm in the final pass |
| 3 | Real OpenAI analysis | DB evidence | **NOT VERIFIED** (latest attempt: `authentication`) |
| 4 | Real correlation | DB evidence | NOT VERIFIED (0 issues in the real DB) |
| 5 | Real recommendation generation | DB evidence | NOT VERIFIED |
| 6 | Real QA retest | DB evidence (non-fake raw run) | NOT VERIFIED |
| 7 | Real security retest | DB evidence (non-fake raw run) | NOT VERIFIED |
| 8 | Report generation | DB + file hashes + leak scan | NOT VERIFIED (0 real reports) |
| 9 | Real browser audit | manual | Pending |
| 10 | Independent MongoDB audit | automatic | PASS (11 expected collections, no extras) |
| 11 | Index verification | automatic | PASS |
| 12 | Traceability audit | automatic | PASS (3 completed assessments) |
| 13 | Security / secret scan | automatic | PASS |
| 14 | Mini E-Commerce immutability | automatic | PASS (HEAD `c736eca7…`, clean) |
