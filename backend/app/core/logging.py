"""Structured logging.

structlog renders every record -- our own and those from uvicorn/sqlalchemy through the
stdlib bridge -- as one JSON object per line on stdout (pretty console output in
development). Context bound with ``structlog.contextvars`` (request_id, user_id, ...)
is merged into every line emitted while that context is active.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.core.config import Settings


def configure_logging(settings: Settings) -> None:
    level = getattr(logging, settings.log_level.upper())

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if settings.use_json_logs
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            renderer,
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # uvicorn installs its own handlers; route them through ours instead. The access log
    # is replaced by the request middleware, which knows the request_id and duration.
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.access").propagate = False
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.stdlib.get_logger(name)
    return logger
