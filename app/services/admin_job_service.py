from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.catalog.registry import GameDataRegistry
from app.core.errors import ApiError
from app.db.models import AdminJobRun
from app.domain.enums import Game
from app.jobs.baselines import precompute_baselines
from app.jobs.benchmarks import run_benchmark_suite
from app.jobs.calibrations import generate_calibration_summary
from app.repositories.core import DataVersionsRepository
from app.services.ai_run_service import AIRunService
from app.services.benchmark_service import BenchmarkService
from app.services.cache_service import CacheService
from app.services.data_version_service import DataVersionService
from app.services.storage_service import StorageService


class AdminJobService:
    def __init__(
        self,
        *,
        session_factory,
        storage_service: StorageService,
        data_version_service: DataVersionService,
        registry: GameDataRegistry,
        cache_service: CacheService,
        benchmark_service: BenchmarkService,
        ai_run_service: AIRunService,
    ) -> None:
        self.session_factory = session_factory
        self.storage_service = storage_service
        self.data_version_service = data_version_service
        self.registry = registry
        self.cache_service = cache_service
        self.benchmark_service = benchmark_service
        self.ai_run_service = ai_run_service

    def create_job(
        self,
        session: Session,
        *,
        job_type: str,
        requested_by: str,
        request_payload: dict[str, Any] | None,
    ) -> AdminJobRun:
        job = AdminJobRun(
            job_type=job_type,
            status="pending",
            request_payload=request_payload,
            result_summary={"requested_by": requested_by},
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return job

    def execute_job(self, *, job_id: UUID) -> None:
        session = self.session_factory()
        try:
            job = session.get(AdminJobRun, job_id)
            if job is None:
                return
            job.status = "running"
            job.started_at = datetime.now(tz=timezone.utc)
            session.add(job)
            session.commit()

            summary = self._run_job(session, job=job)
            artifact_object_key = None
            if summary:
                artifact_object_key = f"admin-jobs/{job.id}/summary.json"
                self.storage_service.write_json(artifact_object_key, summary)
            job.status = "completed"
            job.result_summary = summary
            job.artifact_object_key = artifact_object_key
            job.finished_at = datetime.now(tz=timezone.utc)
            session.add(job)
            session.commit()
        except Exception as exc:
            job = session.get(AdminJobRun, job_id)
            if job is not None:
                job.status = "failed"
                job.result_summary = {"error": str(exc)}
                job.finished_at = datetime.now(tz=timezone.utc)
                session.add(job)
                session.commit()
        finally:
            session.close()

    def get_job(self, session: Session, *, job_id: UUID) -> AdminJobRun:
        job = session.get(AdminJobRun, job_id)
        if job is None:
            raise ApiError("Admin job not found.", status_code=404, code="invalid_input")
        return job

    def to_schema(self, job: AdminJobRun):
        from app.api.schemas.admin import AdminJobRunSchema

        return AdminJobRunSchema(
            id=str(job.id),
            job_type=job.job_type,
            status=job.status,
            summary=(job.result_summary or {}).get("summary") if job.result_summary else None,
            request_payload=job.request_payload,
            result_summary=job.result_summary,
            artifact_object_key=job.artifact_object_key,
            started_at=job.started_at.isoformat() if job.started_at else None,
            finished_at=job.finished_at.isoformat() if job.finished_at else None,
        )

    def _run_job(self, session: Session, *, job: AdminJobRun) -> dict[str, Any]:
        payload = job.request_payload or {}
        if job.job_type == "activate_version":
            repository = DataVersionsRepository(session)
            activated = repository.activate(payload["data_version"])
            return {
                "summary": f"Activated data version {activated.data_version}.",
                "data_version": activated.data_version,
            }
        if job.job_type == "clear_cache":
            cleared = self.cache_service.clear_cache(
                session,
                data_version=payload.get("data_version"),
                game=payload.get("game"),
            )
            return {"summary": f"Cleared {cleared} cache entries.", "cleared_count": cleared}
        if job.job_type == "precompute_baselines":
            summary = precompute_baselines(
                session,
                data_version_service=self.data_version_service,
                registry=self.registry,
                ai_run_service=self.ai_run_service,
                game=Game(payload["game"]),
                data_version=payload["data_version"],
                provider_name=payload["provider_name"],
                model_name=payload["model_name"],
            )
            summary["summary"] = (
                f"Precomputed baselines for {summary['champion_count']} champions "
                f"in {summary['game']}."
            )
            return summary
        if job.job_type == "generate_calibration":
            results = []
            for model_ref in payload["models"]:
                for game in payload["games"]:
                    results.append(
                        generate_calibration_summary(
                            session,
                            storage_service=self.storage_service,
                            data_version_service=self.data_version_service,
                            registry=self.registry,
                            provider_name=model_ref["provider_name"],
                            model_name=model_ref["model_name"],
                            game=Game(game),
                            data_version=payload["data_version"],
                        )
                    )
            return {
                "summary": f"Generated {len(results)} calibration summaries.",
                "results": results,
            }
        if job.job_type == "run_benchmarks":
            summary = run_benchmark_suite(
                session,
                benchmark_service=self.benchmark_service,
                ai_run_service=self.ai_run_service,
                storage_service=self.storage_service,
                dataset_id=payload["dataset_id"],
                models=payload["models"],
            )
            summary["summary"] = (
                f"Completed benchmark run for {len(summary['model_runs'])} model(s)."
            )
            return summary
        raise ApiError("Unsupported admin job.", status_code=400, code="invalid_input")
