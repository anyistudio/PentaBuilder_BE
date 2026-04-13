from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_admin_job_service,
    get_admin_user,
    get_db_session,
    get_metrics_service,
)
from app.api.schemas.admin import (
    ActivateDataVersionRequest,
    AdminJobAcceptedPayload,
    AdminJobDetailPayload,
    CacheClearRequest,
    GenerateCalibrationsRequest,
    PrecomputeBaselinesRequest,
    RunBenchmarksRequest,
)
from app.api.schemas.common import ApiResponse
from app.services.admin_job_service import AdminJobService
from app.services.metrics_service import MetricsService

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _schedule_job(
    *,
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session,
    admin_user: str,
    admin_job_service: AdminJobService,
    job_type: str,
    payload: dict,
) -> ApiResponse[AdminJobAcceptedPayload]:
    job = admin_job_service.create_job(
        session,
        job_type=job_type,
        requested_by=admin_user,
        request_payload=payload,
    )
    background_tasks.add_task(admin_job_service.execute_job, job_id=job.id)
    return ApiResponse[AdminJobAcceptedPayload](
        request_id=request.state.request_id,
        data=AdminJobAcceptedPayload(job_id=str(job.id), status="accepted"),
    )


@router.post("/data-versions/activate", status_code=status.HTTP_202_ACCEPTED)
def activate_data_version(
    request: Request,
    payload: ActivateDataVersionRequest,
    background_tasks: BackgroundTasks,
    session: Annotated[Session, Depends(get_db_session)],
    admin_user: Annotated[str, Depends(get_admin_user)],
    admin_job_service: Annotated[AdminJobService, Depends(get_admin_job_service)],
) -> ApiResponse[AdminJobAcceptedPayload]:
    return _schedule_job(
        request=request,
        background_tasks=background_tasks,
        session=session,
        admin_user=admin_user,
        admin_job_service=admin_job_service,
        job_type="activate_version",
        payload=payload.model_dump(mode="json"),
    )


@router.post("/cache/clear", status_code=status.HTTP_202_ACCEPTED)
def clear_cache(
    request: Request,
    payload: CacheClearRequest,
    background_tasks: BackgroundTasks,
    session: Annotated[Session, Depends(get_db_session)],
    admin_user: Annotated[str, Depends(get_admin_user)],
    admin_job_service: Annotated[AdminJobService, Depends(get_admin_job_service)],
) -> ApiResponse[AdminJobAcceptedPayload]:
    return _schedule_job(
        request=request,
        background_tasks=background_tasks,
        session=session,
        admin_user=admin_user,
        admin_job_service=admin_job_service,
        job_type="clear_cache",
        payload=payload.model_dump(mode="json", exclude_none=True),
    )


@router.post("/jobs/precompute-baselines", status_code=status.HTTP_202_ACCEPTED)
def precompute_baselines(
    request: Request,
    payload: PrecomputeBaselinesRequest,
    background_tasks: BackgroundTasks,
    session: Annotated[Session, Depends(get_db_session)],
    admin_user: Annotated[str, Depends(get_admin_user)],
    admin_job_service: Annotated[AdminJobService, Depends(get_admin_job_service)],
) -> ApiResponse[AdminJobAcceptedPayload]:
    return _schedule_job(
        request=request,
        background_tasks=background_tasks,
        session=session,
        admin_user=admin_user,
        admin_job_service=admin_job_service,
        job_type="precompute_baselines",
        payload=payload.model_dump(mode="json"),
    )


@router.post("/jobs/generate-calibrations", status_code=status.HTTP_202_ACCEPTED)
def generate_calibrations(
    request: Request,
    payload: GenerateCalibrationsRequest,
    background_tasks: BackgroundTasks,
    session: Annotated[Session, Depends(get_db_session)],
    admin_user: Annotated[str, Depends(get_admin_user)],
    admin_job_service: Annotated[AdminJobService, Depends(get_admin_job_service)],
) -> ApiResponse[AdminJobAcceptedPayload]:
    return _schedule_job(
        request=request,
        background_tasks=background_tasks,
        session=session,
        admin_user=admin_user,
        admin_job_service=admin_job_service,
        job_type="generate_calibration",
        payload=payload.model_dump(mode="json"),
    )


@router.post("/jobs/run-benchmarks", status_code=status.HTTP_202_ACCEPTED)
def run_benchmarks(
    request: Request,
    payload: RunBenchmarksRequest,
    background_tasks: BackgroundTasks,
    session: Annotated[Session, Depends(get_db_session)],
    admin_user: Annotated[str, Depends(get_admin_user)],
    admin_job_service: Annotated[AdminJobService, Depends(get_admin_job_service)],
) -> ApiResponse[AdminJobAcceptedPayload]:
    return _schedule_job(
        request=request,
        background_tasks=background_tasks,
        session=session,
        admin_user=admin_user,
        admin_job_service=admin_job_service,
        job_type="run_benchmarks",
        payload=payload.model_dump(mode="json"),
    )


@router.get("/jobs/{job_id}")
def get_admin_job(
    request: Request,
    job_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    admin_user: Annotated[str, Depends(get_admin_user)],
    admin_job_service: Annotated[AdminJobService, Depends(get_admin_job_service)],
) -> ApiResponse[AdminJobDetailPayload]:
    del admin_user
    job = admin_job_service.get_job(session, job_id=job_id)
    return ApiResponse[AdminJobDetailPayload](
        request_id=request.state.request_id,
        data=AdminJobDetailPayload(job=admin_job_service.to_schema(job)),
    )


@router.get("/metrics")
def get_metrics_snapshot(
    request: Request,
    admin_user: Annotated[str, Depends(get_admin_user)],
    metrics_service: Annotated[MetricsService, Depends(get_metrics_service)],
) -> ApiResponse[dict]:
    del admin_user
    return ApiResponse[dict](
        request_id=request.state.request_id,
        data=metrics_service.snapshot(),
    )
