"""Re-executes the exact test behind a finding and compares before/after (Phase 9).

Pure logic: turn a stored Phase 8 retest specification into a scoped
execution plan for an *existing* engine (``plan.py``), and turn that
engine's normalized output into a deterministic PASS / FAIL verdict using
the Phase 6 correlation key or the exact QA check (``verdict.py``).

No model, no shell, no network, no persistence here - the service runs the
engines through QaService / SecurityService and stores the result.
"""
