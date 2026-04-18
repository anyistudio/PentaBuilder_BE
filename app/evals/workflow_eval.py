"""Backward-compatible façade for the AI workflow evaluation package.

All public symbols are re-exported from their respective sub-modules so that
existing callers (e.g. scripts/run_ai_workflow_eval.py) require zero changes.

Internal layout
---------------
models.py     — EvalModelRef, EvalSeedRun, EvalCase, parse_model_refs
test_cases.py — build_eval_cases (split per-feature for easy editing)
runner.py     — run_local_workflow_eval, create_eval_app, _run_one_case
reporter.py   — render_markdown_report, build_default_output_path
"""

from __future__ import annotations

from app.evals.models import (  # noqa: F401
    EvalCase,
    EvalModelRef,
    EvalSeedRun,
    default_model_refs,
    parse_model_refs,
)
from app.evals.reporter import (  # noqa: F401
    build_default_output_path,
    render_markdown_report,
)
from app.evals.runner import (  # noqa: F401
    create_eval_app,
    run_local_workflow_eval,
)
from app.evals.test_cases import build_eval_cases  # noqa: F401

__all__ = [
    # models
    "EvalModelRef",
    "EvalSeedRun",
    "EvalCase",
    "default_model_refs",
    "parse_model_refs",
    # test_cases
    "build_eval_cases",
    # runner
    "create_eval_app",
    "run_local_workflow_eval",
    # reporter
    "render_markdown_report",
    "build_default_output_path",
]
