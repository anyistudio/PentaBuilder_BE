from pathlib import Path
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.config import BASE_DIR, Settings
from app.core.errors import ApiError
from app.db.models import AIRun, BenchmarkCase, BenchmarkDataset
from app.domain.enums import Game, Language, RunType, TerminologyStyle
from app.domain.match_context import MatchContext, ResponsePreferences
from app.services.storage_service import StorageService


class BenchmarkService:
    def __init__(self, settings: Settings, storage_service: StorageService) -> None:
        self.settings = settings
        self.storage_service = storage_service

    def sync_local_datasets(self, session: Session) -> list[BenchmarkDataset]:
        root = Path(self.settings.benchmark_local_root)
        if not root.is_absolute():
            root = BASE_DIR / root
        if not root.exists():
            return []

        synced: list[BenchmarkDataset] = []
        for file_path in sorted(root.glob("*.json")):
            payload = self.storage_service.read_json_from_root(str(root), file_path.name)
            dataset = self._upsert_dataset(session, payload)
            synced.append(dataset)
        return synced

    def get_dataset(self, session: Session, *, dataset_id: str) -> BenchmarkDataset:
        try:
            parsed_id = UUID(dataset_id)
        except ValueError as exc:
            raise ApiError(
                "Benchmark dataset not found.", status_code=404, code="invalid_input"
            ) from exc
        dataset = session.get(BenchmarkDataset, parsed_id)
        if dataset is None:
            raise ApiError("Benchmark dataset not found.", status_code=404, code="invalid_input")
        return dataset

    def build_case_request(self, case: BenchmarkCase) -> dict[str, Any]:
        input_context = case.input_context or {}
        context = MatchContext(**input_context["context"])
        response_preferences = ResponsePreferences(
            **input_context.get(
                "response_preferences",
                {
                    "language": Language.ZH_CN.value,
                    "terminology_style": TerminologyStyle.OFFICIAL.value,
                },
            )
        )
        return {
            "context": context,
            "response_preferences": response_preferences,
            "payload": input_context.get("payload", {}),
        }

    def grade_case(
        self, case: BenchmarkCase, *, result: dict[str, Any], run: AIRun
    ) -> dict[str, Any]:
        expected = case.expected_output or {}
        rubric = case.grading_rubric or {}
        components: list[float] = []
        details: dict[str, Any] = {}

        score_min = expected.get("score_min")
        if score_min is not None:
            actual_score = run.score_value or 0
            components.append(
                1.0 if actual_score >= score_min else max(actual_score / max(score_min, 1), 0.0)
            )
            details["score"] = {"expected_min": score_min, "actual": actual_score}

        required_build_items = expected.get("required_build_items", [])
        if required_build_items:
            build = result.get("build") or []
            coverage = len(set(required_build_items) & set(build)) / len(required_build_items)
            components.append(coverage)
            details["required_build_items"] = {
                "required": required_build_items,
                "actual": build,
                "coverage": coverage,
            }

        summary_contains_any = expected.get("summary_contains_any", [])
        if summary_contains_any:
            summary_text = str(result.get("summary") or "").lower()
            hit = any(keyword.lower() in summary_text for keyword in summary_contains_any)
            components.append(1.0 if hit else 0.0)
            details["summary_contains_any"] = {
                "required": summary_contains_any,
                "actual": result.get("summary"),
            }

        exact_slot_match = expected.get("slot_equals")
        if exact_slot_match:
            build = result.get("build") or []
            slot_index = int(exact_slot_match["slot_index"])
            actual_item = build[slot_index] if slot_index < len(build) else None
            hit = actual_item == exact_slot_match["item_slug"]
            components.append(1.0 if hit else 0.0)
            details["slot_equals"] = {
                "expected": exact_slot_match["item_slug"],
                "actual": actual_item,
            }

        score = round(sum(components) / len(components), 4) if components else 1.0
        pass_threshold = float(rubric.get("pass_threshold", 0.7))
        return {
            "score": score,
            "passed": score >= pass_threshold,
            "summary": {
                "score": score,
                "pass_threshold": pass_threshold,
                "details": details,
            },
        }

    def _upsert_dataset(self, session: Session, payload: dict[str, Any]) -> BenchmarkDataset:
        name = payload["name"]
        dataset = session.scalar(sa.select(BenchmarkDataset).where(BenchmarkDataset.name == name))
        if dataset is None:
            dataset = BenchmarkDataset(name=name)
        dataset.game = Game(payload["game"]).value
        dataset.data_version = payload["data_version"]
        dataset.description = payload.get("description")
        dataset.labeling_status = payload.get("labeling_status", "draft")
        session.add(dataset)
        session.commit()
        session.refresh(dataset)

        session.execute(sa.delete(BenchmarkCase).where(BenchmarkCase.dataset_id == dataset.id))
        for case_payload in payload.get("cases", []):
            session.add(
                BenchmarkCase(
                    dataset_id=dataset.id,
                    case_key=case_payload["case_key"],
                    run_type=RunType(case_payload["run_type"]).value,
                    input_context=case_payload["input_context"],
                    expected_output=case_payload.get("expected_output", {}),
                    grading_rubric=case_payload.get("grading_rubric", {}),
                )
            )
        session.commit()
        session.refresh(dataset)
        return dataset
