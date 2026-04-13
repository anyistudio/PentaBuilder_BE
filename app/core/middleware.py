import logging
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.request_context import reset_request_id, set_request_id

LOGGER = logging.getLogger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        token = set_request_id(request_id)
        started_at = time.perf_counter()

        LOGGER.info(
            "request_started",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
            },
        )

        try:
            response = await call_next(request)
        finally:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            metrics_service = getattr(request.app.state, "metrics_service", None)
            if metrics_service is not None:
                metrics_service.record_request(
                    success=200 <= getattr(locals().get("response"), "status_code", 500) < 500
                )
            LOGGER.info(
                "request_completed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": getattr(locals().get("response"), "status_code", 500),
                    "duration_ms": duration_ms,
                    "user_id": getattr(request.state, "user_id", None),
                    "session_id": getattr(request.state, "session_id", None),
                    "run_id": getattr(request.state, "run_id", None),
                },
            )
            reset_request_id(token)

        response.headers["X-Request-ID"] = request_id
        return response
