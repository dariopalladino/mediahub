"""Structured logging setup using structlog + Rich."""
from __future__ import annotations

import logging
from pathlib import Path

import structlog
from rich.console import Console
from rich.logging import RichHandler


def setup_logging(log_level: str = "INFO", log_file: Path | None = None) -> None:
    """Configure structlog with Rich console output and optional file rotation.

    Args:
        log_level: Logging level string (DEBUG/INFO/WARNING/ERROR).
        log_file: Optional path for rotating file log.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    handlers: list[logging.Handler] = [
        RichHandler(
            console=Console(stderr=True),
            rich_tracebacks=True,
            show_time=True,
            show_level=True,
        )
    ]

    if log_file is not None:
        from logging.handlers import RotatingFileHandler

        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5)
        fh.setFormatter(logging.Formatter("%(message)s"))
        handlers.append(fh)

    logging.basicConfig(level=level, handlers=handlers, format="%(message)s")

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
