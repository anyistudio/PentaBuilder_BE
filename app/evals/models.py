from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.domain.enums import RunType
from app.domain.match_context import MatchContext, ResponsePreferences

# ---------------------------------------------------------------------------
# Core data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvalModelRef:
    provider_name: str
    model_name: str

    @property
    def label(self) -> str:
        return f"{self.provider_name}/{self.model_name}"


@dataclass(frozen=True)
class EvalSeedRun:
    """A preliminary AI run whose output becomes the reply context for the real run."""

    run_type: RunType
    payload: dict[str, Any]


@dataclass(frozen=True)
class EvalCase:
    case_key: str
    feature: RunType
    description: str
    context: MatchContext
    payload: dict[str, Any]
    response_preferences: ResponsePreferences
    reply_seed: EvalSeedRun | None = None


# ---------------------------------------------------------------------------
# Model reference parsing
# ---------------------------------------------------------------------------


def parse_model_refs(model_args: list[str] | None, settings: Settings) -> list[EvalModelRef]:
    """Return a deduplicated list of EvalModelRef to evaluate.

    Falls back to ``default_model_refs`` when *model_args* is empty/None.
    """
    if not model_args:
        refs = default_model_refs(settings)
        if not refs:
            raise ValueError("No evaluation models are configured.")
        return refs

    return _parse_model_ref_strings(model_args)


def default_model_refs(settings: Settings) -> list[EvalModelRef]:
    """Build the default model list from application settings."""
    if settings.all_models_list:
        return _parse_model_ref_strings(settings.all_models_list)

    ordered_refs = [
        EvalModelRef(
            settings.resolved_primary_reasoning_provider,
            settings.resolved_primary_reasoning_model,
        ),
        EvalModelRef(
            settings.resolved_fast_reasoning_provider,
            settings.resolved_fast_reasoning_model,
        ),
    ]
    if settings.openai_api_key.get_secret_value() not in {"", "replace-me"}:
        ordered_refs.extend(
            [
                EvalModelRef("openai", "gpt-4.1"),
                EvalModelRef("openai", "gpt-4.1-mini"),
            ]
        )

    return _deduplicate(ordered_refs)


def _parse_model_ref_strings(model_args: list[str]) -> list[EvalModelRef]:
    refs: list[EvalModelRef] = []
    for raw_ref in model_args:
        provider_name, separator, model_name = raw_ref.partition(":")
        provider_name = provider_name.strip()
        model_name = model_name.strip()
        if separator != ":" or not provider_name or not model_name:
            raise ValueError(
                f"Invalid model reference {raw_ref!r}. Use the format provider:model_name."
            )
        refs.append(EvalModelRef(provider_name=provider_name, model_name=model_name))

    return _deduplicate(refs)


def _deduplicate(refs: list[EvalModelRef]) -> list[EvalModelRef]:
    unique: list[EvalModelRef] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        key = (ref.provider_name, ref.model_name)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ref)
    return unique
