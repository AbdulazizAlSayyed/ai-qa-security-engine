"""Application discovery: what pages, links, forms and controls a target has.

Four modules, each with one job:

* :mod:`app.engines.discovery.urls` - what counts as the same page, the same
  origin, and the same route. Pure functions, no browser.
* :mod:`app.engines.discovery.models` - the structured facts a discovery
  produces. Plain dataclasses, no HTTP and no MongoDB.
* :mod:`app.engines.discovery.extraction` - one constant, read-only script
  that turns a rendered DOM into those facts.
* :mod:`app.engines.discovery.crawler` - a bounded breadth-first walk of one
  target with a real browser.

The engine is deterministic and target-agnostic: nothing here knows a page,
a route, a selector or a workflow of any particular application, and no
model is called. It reads; it never changes the application it is looking at.
"""
