import logging
from enum import Enum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.request_context import get_request_id

LOGGER = logging.getLogger(__name__)


class ErrorType(str, Enum):
    DOMAIN = "domain_error"
    INTEGRATION = "integration_error"
    API = "api_error"


class ErrorDetail(BaseModel):
    type: ErrorType
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str | None = None


class AppError(Exception):
    status_code = 400
    code = "app_error"
    error_type = ErrorType.API

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        self.status_code = status_code or self.status_code
        self.code = code or self.code


class DomainError(AppError):
    status_code = 400
    code = "domain_error"
    error_type = ErrorType.DOMAIN


class IntegrationError(AppError):
    status_code = 502
    code = "integration_error"
    error_type = ErrorType.INTEGRATION


class ApiError(AppError):
    status_code = 400
    code = "api_error"
    error_type = ErrorType.API


def _request_id_from_request(request: Request) -> str | None:
    return getattr(request.state, "request_id", None) or get_request_id()


def _build_error_response(
    *,
    request_id: str | None,
    status_code: int,
    error_type: ErrorType,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorDetail(
            type=error_type,
            code=code,
            message=message,
            details=details,
        ),
        request_id=request_id,
    )
    response = JSONResponse(status_code=status_code, content=payload.model_dump(exclude_none=True))
    if request_id:
        response.headers["X-Request-ID"] = request_id
    return response


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        request_id = _request_id_from_request(request)
        return _build_error_response(
            request_id=request_id,
            status_code=exc.status_code,
            error_type=exc.error_type,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        request_id = _request_id_from_request(request)
        return _build_error_response(
            request_id=request_id,
            status_code=422,
            error_type=ErrorType.API,
            code="validation_error",
            message="Request validation failed.",
            details={"issues": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        request_id = _request_id_from_request(request)
        LOGGER.exception("unhandled_exception", extra={"request_id": request_id})
        return _build_error_response(
            request_id=request_id,
            status_code=500,
            error_type=ErrorType.API,
            code="internal_server_error",
            message="Internal server error.",
        )
