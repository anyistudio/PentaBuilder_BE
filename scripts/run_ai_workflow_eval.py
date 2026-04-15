from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Direct script execution needs the repo root on sys.path before importing app modules.
from app.core.config import get_settings  # noqa: E402
from app.domain.enums import RunType  # noqa: E402
from app.evals.workflow_eval import (  # noqa: E402
    build_default_output_path,
    create_eval_app,
    parse_model_refs,
    run_local_workflow_eval,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run local AI workflow evaluation across multiple models."
    )
    parser.add_argument(
        "--model",
        action="append",
        dest="models",
        help="Provider/model pair in provider:model_name format. Repeat for multiple models.",
    )
    parser.add_argument(
        "--feature",
        action="append",
        dest="features",
        choices=[run_type.value for run_type in RunType],
        help="Limit the run to one or more specific AI features.",
    )
    parser.add_argument(
        "--data-version",
        dest="data_version",
        help="Override the active data_version.",
    )
    parser.add_argument(
        "--output",
        dest="output",
        help=(
            "Write the markdown report to this path instead of the default "
            "evaluation_reports directory."
        ),
    )
    parser.add_argument(
        "--debug-llm",
        action="store_true",
        help="Keep verbose LLM IO debug logging enabled while running the evaluation.",
    )
    args = parser.parse_args()

    settings = get_settings()
    model_refs = parse_model_refs(args.models, settings)
    app = create_eval_app(debug_llm=args.debug_llm)
    session_factory = app.state.session_factory

    with session_factory() as session:
        active_version = app.state.data_version_service.get_active_version(session)
    data_version = args.data_version or active_version.data_version
    output_path = Path(args.output) if args.output else build_default_output_path(data_version)
    feature_filter = {RunType(feature) for feature in args.features} if args.features else None

    print(
        "Running AI workflow evaluation for models: " + ", ".join(ref.label for ref in model_refs)
    )
    print(f"Using data_version: {data_version}")
    if feature_filter:
        print("Feature filter: " + ", ".join(run_type.value for run_type in feature_filter))

    report = run_local_workflow_eval(
        session_factory=session_factory,
        ai_run_service=app.state.ai_run_service,
        data_version=data_version,
        model_refs=model_refs,
        output_path=output_path,
        feature_filter=feature_filter,
    )
    print(
        "Completed AI workflow evaluation. "
        f"Summary rows: {len(report['summary']['feature_model_summaries'])}. "
        f"Report written to {output_path}"
    )


if __name__ == "__main__":
    main()
