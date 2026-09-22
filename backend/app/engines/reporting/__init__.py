"""Reports (Phase 10): traceability audit, report assembly and rendering.

Pure functions over records that were already persisted by Phases 1-9.
Nothing in this package runs a test, scans, opens a browser, calls a
target or a model, runs correlation / recommendations / retests, or writes
to the database. ``ReportService`` loads the data, calls these functions
and persists the result in ``reports``.
"""
