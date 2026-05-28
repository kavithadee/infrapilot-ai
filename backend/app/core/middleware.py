import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import get_logger

logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Log every HTTP request: method, path, status code, and latency.

    Emits a single structured JSON line per request:
        {"ts": "...", "level": "INFO", "event": "http_request",
         "method": "POST", "path": "/incidents", "status": 202, "latency_ms": 41}

    /health is logged at DEBUG to avoid noise in production log streams.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.time()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception as exc:
            logger.error(
                "http_request_unhandled_error",
                method=request.method,
                path=request.url.path,
                error=str(exc),
            )
            raise
        finally:
            latency_ms = int((time.time() - start) * 1000)
            level = "debug" if request.url.path == "/health" else "info"
            getattr(logger, level)(
                "http_request",
                method=request.method,
                path=request.url.path,
                status=status_code,
                latency_ms=latency_ms,
            )
