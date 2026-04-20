from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.evals.recommend_full_build_benchmark import (  # noqa: E402
    DEFAULT_PRICE_FILE_PATH,
    build_default_output_dir,
    filter_model_refs,
    load_model_refs_from_env_file,
    run_recommend_full_build_benchmark,
)
from app.evals.runner import create_eval_app  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark recommend_full_build latency and outputs "
            "across all configured models."
        )
    )
    parser.add_argument(
        "--data-version",
        dest="data_version",
        help="Override the active data_version.",
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        help=(
            "Write benchmark artifacts into this directory instead of "
            "the default timestamped path."
        ),
    )
    parser.add_argument(
        "--price-file",
        dest="price_file",
        default=str(DEFAULT_PRICE_FILE_PATH),
        help="Path to the JSON token-price template used for estimated cost calculation.",
    )
    parser.add_argument(
        "--provider",
        dest="providers",
        action="append",
        help=(
            "Only run models from the given provider. "
            "Repeat the flag or pass a comma-separated list, e.g. "
            "`--provider google` or `--provider google,openai`."
        ),
    )
    parser.add_argument(
        "--model",
        dest="models",
        action="append",
        help=(
            "Only run the given model or models. "
            "Repeat the flag or pass a comma-separated list, e.g. "
            "`--model gemini-2.5-flash` or "
            "`--model google/gemini-2.5-flash,google:gemini-3-flash-preview`."
        ),
    )
    parser.add_argument(
        "--debug-llm",
        action="store_true",
        help="Keep verbose LLM debug logging enabled while the benchmark runs.",
    )
    args = parser.parse_args()

    app = create_eval_app(debug_llm=args.debug_llm)
    session_factory = app.state.session_factory
    model_refs = filter_model_refs(
        model_refs=load_model_refs_from_env_file(),
        providers=args.providers,
        models=args.models,
    )

    with session_factory() as session:
        active_version = app.state.data_version_service.get_active_version(session)
    data_version = args.data_version or active_version.data_version
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else build_default_output_dir(data_version)
    )
    price_file_path = Path(args.price_file)

    print(
        "Running recommend_full_build benchmark for models: "
        + ", ".join(ref.label for ref in model_refs)
    )
    if args.providers:
        print(f"Provider filter: {', '.join(args.providers)}")
    if args.models:
        print(f"Model filter: {', '.join(args.models)}")
    print(f"Using data_version: {data_version}")
    print(f"Output directory: {output_dir}")
    print(f"Price file: {price_file_path}")

    bundle = run_recommend_full_build_benchmark(
        session_factory=session_factory,
        ai_run_service=app.state.ai_run_service,
        data_version=data_version,
        model_refs=model_refs,
        output_dir=output_dir,
        price_file_path=price_file_path,
        show_progress=True,
        show_failure_logs=True,
    )

    print(
        "Completed recommend_full_build benchmark. "
        f"Saved report JSON to {bundle['output_paths']['report_json']} "
        f"and Markdown to {bundle['output_paths']['report_markdown']}"
    )


if __name__ == "__main__":
    main()
