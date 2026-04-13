from app.catalog.registry import CatalogSnapshot
from app.domain.enums import RunType
from app.domain.match_context import MatchContext, ResponsePreferences


def build_prompt(
    *,
    run_type: RunType,
    context: MatchContext,
    response_preferences: ResponsePreferences,
    operation_context: dict,
    baseline_summary: str | None,
    reference_summary: str | None,
    calibration_summary: str | None,
    snapshot: CatalogSnapshot,
) -> str:
    game_label = "LoL PC" if context.game.value == "lol" else "Wild Rift"
    localization_note = "Use the user's target language directly. Keep slugs canonical."
    return "\n".join(
        [
            f"Run type: {run_type.value}",
            f"Target game: {game_label}",
            f"Target language: {response_preferences.language.value}",
            f"Terminology style: {response_preferences.terminology_style.value}",
            "Do not mix LoL PC and Wild Rift terminology or items.",
            localization_note,
            f"Current data version: {snapshot.data_version}",
            f"Context: {context.model_dump_json()}",
            f"Payload: {operation_context}",
            f"Baseline summary: {baseline_summary}",
            f"Reference summary: {reference_summary}",
            f"Calibration summary: {calibration_summary}",
        ]
    )
