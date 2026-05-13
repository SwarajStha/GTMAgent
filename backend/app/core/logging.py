"""Structured logging setup.

Configures a JSON-friendly logging format suitable for container stdout.
"""
from __future__ import annotations

import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    """Configure root logger for the application."""
    root = logging.getLogger()
    root.setLevel(level.upper())

    if root.handlers:
        return

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    root.addHandler(handler)
