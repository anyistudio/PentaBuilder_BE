from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import BenchmarkCase, BenchmarkResult, BenchmarkRun
from app.domain.enums import RunType
from app.services.ai_run_service import AIRunService
from app.services.benchmark_service import BenchmarkService
from app.services.storage_service import StorageService


def run_benchmark_suite(
    session: Session,
    *,
    benchmark_service: BenchmarkService,
    ai_run_service: AIRunService,
    storage_service: StorageService,
    dataset_id: str,
    models: list[dict[str, str]],
) -> dict[str, object]:
    benchmark_service.sync_local_datasets(session)
    dataset = benchmark_service.get_dataset(session, dataset_id=dataset_id)
    cases = list(
        session.scalars(
            sa.select(BenchmarkCase)
            .where(BenchmarkCase.dataset_id == dataset.id)
            .order_by(BenchmarkCase.case_key)
        )
    )
    summaries: list[dict[str, Any]] = []

    for model_ref in models:
        provider_name = model_ref["provider_name"]
        model_name = model_ref["model_name"]
        benchmark_run = BenchmarkRun(
            dataset_id=dataset.id,
            provider_name=provider_name,
            model_name=model_name,
            status="running",
            started_at=datetime.now(tz=timezone.utc),
        )
        session.add(benchmark_run)
        session.commit()
        session.refresh(benchmark_run)

        case_scores: list[float] = []
        latencies: list[int] = []
        costs: list[float] = []
        passed_count = 0

        for case in cases:
            case_request = benchmark_service.build_case_request(case)
            run, _ = ai_run_service.create_run(
                session,
                user=None,
                session_id=None,
                run_type=RunType(case.run_type),
                context=case_request["context"],
                response_preferences=case_request["response_preferences"],
                operation_context=case_request["payload"],
                stream=False,
                use_cache=False,
            )
            result = ai_run_service.execute_run(
                session,
                run=run,
                context=case_request["context"],
                response_preferences=case_request["response_preferences"],
                operation_context=case_request["payload"],
                provider_name_override=provider_name,
                model_name_override=model_name,
            )
            graded = benchmark_service.grade_case(case, result=result, run=run)
            benchmark_result = BenchmarkResult(
                benchmark_run_id=benchmark_run.id,
                case_id=case.id,
                ai_run_id=run.id,
                score=graded["score"],
                passed=graded["passed"],
                latency_ms=run.latency_ms,
                cost_usd=run.cost_usd,
                result_summary=graded["summary"],
                artifact_object_key=run.artifact_object_key,
            )
            session.add(benchmark_result)
            session.commit()

            case_scores.append(float(graded["score"]))
            if graded["passed"]:
                passed_count += 1
            if run.latency_ms is not None:
                latencies.append(run.latency_ms)
            if run.cost_usd is not None:
                costs.append(float(run.cost_usd))

        accuracy_score = passed_count / len(cases) if cases else 0.0
        avg_latency_ms = round(sum(latencies) / len(latencies)) if latencies else None
        avg_cost_usd = round(sum(costs) / len(costs), 6) if costs else None
        summary_payload = {
            "dataset_id": str(dataset.id),
            "provider_name": provider_name,
            "model_name": model_name,
            "case_count": len(cases),
            "accuracy_score": accuracy_score,
            "avg_case_score": round(sum(case_scores) / len(case_scores), 4) if case_scores else 0.0,
            "avg_latency_ms": avg_latency_ms,
            "avg_cost_usd": avg_cost_usd,
        }
        object_key = f"benchmarks/{benchmark_run.id}/summary.json"
        storage_service.write_json(object_key, summary_payload)

        benchmark_run.status = "completed"
        benchmark_run.summary_object_key = object_key
        benchmark_run.avg_latency_ms = avg_latency_ms
        benchmark_run.avg_cost_usd = avg_cost_usd
        benchmark_run.accuracy_score = accuracy_score
        benchmark_run.finished_at = datetime.now(tz=timezone.utc)
        session.add(benchmark_run)
        session.commit()

        summaries.append(summary_payload)

    return {
        "dataset_id": str(dataset.id),
        "dataset_name": dataset.name,
        "model_runs": summaries,
    }
