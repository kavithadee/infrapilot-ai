import json
import logging
import sys
from datetime import datetime, timezone


class _JsonFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        # Merge any extra kwargs passed via get_logger().info("event", key=val)
        for key, val in record.__dict__.items():
            if key not in {
                "ts", "level", "logger", "event",
                "name", "msg", "args", "levelname", "levelno",
                "pathname", "filename", "module", "exc_info",
                "exc_text", "stack_info", "lineno", "funcName",
                "created", "msecs", "relativeCreated", "thread",
                "threadName", "processName", "process", "message",
            }:
                payload[key] = val

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def get_logger(name: str) -> "BoundLogger":
    """Return a logger that supports structured kwargs: logger.info('event', key=val)."""
    return BoundLogger(name)


class BoundLogger:
    """
    Thin wrapper around stdlib logger that accepts keyword arguments and
    injects them as extra fields into the JSON output.

    Usage:
        logger = get_logger(__name__)
        logger.info("tool_call_complete", tool="get_recent_deploys", latency_ms=42)
    """

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    def _log(self, level: int, event: str, **kwargs) -> None:
        self._logger.log(level, event, extra=kwargs)

    def debug(self, event: str, **kwargs) -> None:
        self._log(logging.DEBUG, event, **kwargs)

    def info(self, event: str, **kwargs) -> None:
        self._log(logging.INFO, event, **kwargs)

    def warning(self, event: str, **kwargs) -> None:
        self._log(logging.WARNING, event, **kwargs)

    def error(self, event: str, **kwargs) -> None:
        self._log(logging.ERROR, event, **kwargs)

    def critical(self, event: str, **kwargs) -> None:
        self._log(logging.CRITICAL, event, **kwargs)


def configure_logging(level: str = "INFO") -> None:
    """
    Configure root logger with JSON formatter. Call once from main.py on startup.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
