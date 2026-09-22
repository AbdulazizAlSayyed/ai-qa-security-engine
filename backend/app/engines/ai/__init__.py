"""Evidence-grounded AI analysis and the provider abstraction.

Analysis reads normalized evidence only. Nothing in this package runs a
test, scans, opens a browser, calls a target, executes model output or
writes files; it turns evidence into a prompt, sends it through an
``AIProvider``, and validates what comes back.
"""
