"""Structured logging configuration using structlog."""

import logging

import structlog


def configure_logging(json_output: bool = False) -> None:
    """Configure structlog for the application.

    Args:
        json_output: If True, use JSONRenderer for machine-readable output.
                     If False (default), use ConsoleRenderer for development.
    """
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str):
    """Get a bound logger with module context.

    Args:
        name: Module name to bind to the logger.

    Returns:
        A structlog bound logger with module=name in context.
    """
    return structlog.get_logger().bind(module=name)
