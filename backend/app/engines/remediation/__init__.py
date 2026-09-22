"""Advisory recommendation contract (Phase 8).

Developer-oriented recommendations generated through the existing
``AIAnalysisService`` from stored evidence, the completed AI analysis and the
prioritized issues. Everything here is advisory: this package defines the
prompt, the strict output schema and its validation, and the structured retest
specification that Phase 9 will consume. It executes nothing, changes nothing,
and never talks to a model directly.
"""
