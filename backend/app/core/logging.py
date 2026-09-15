"""Logging configuration.

One place decides the format and level for the whole backend, so engine
output, request logs and tool runner output all read the same way in a
single terminal.
"""

from __future__ import annotations

import logging
import sys

from app.core.config import get_settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-38s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def configure_logging(force: bool = False) -> None:
    """Install the root handler. Idempotent unless ``force`` is set."""
    global _configured
    if _configured and not force:
        return

    settings = get_settings()
    level = getattr(logging, settings.log_level, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # PyMongo's topology monitor is chatty at DEBUG and drowns out our own
    # engine output during a scan.
    logging.getLogger("pymongo").setLevel(max(level, logging.WARNING))

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a module logger. Use ``get_logger(__name__)``."""
    return logging.getLogger(name)
