"""Requirement candidate extraction.

Two readers of documents, both offline with respect to the target:

* :mod:`app.engines.requirements.prompts` and
  :mod:`app.engines.requirements.validation` turn a business document into
  *candidates* through the platform's existing ``AIProvider``.
* :mod:`app.engines.requirements.openapi_import` does the same for an
  OpenAPI document with no model involved at all - it is a parser.

Neither one writes to MongoDB, allocates a REQ key, calls a tool, or
contacts the application being described. A candidate becomes a requirement
only when a human posts it back through the ordinary create path.
"""
