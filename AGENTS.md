# PentaBuilder BE Agent Guide

## Project Goal

`PentaBuilder_BE` is the backend monolith for the PentaBuilder product.

Its job is to provide:

- REST + SSE APIs
- session persistence
- AI run orchestration
- cache and leaderboard updates
- baseline/calibration/benchmark jobs

It is not the source-of-truth store for full game data. Game data is loaded from versioned processed JSON in local storage or S3.

## Core Rules

### 1. Use `uv` for package management and command execution

Do not mix package managers.

Use:

- `uv sync`
- `uv run uvicorn ...`
- `uv run pytest`
- `uv run ruff check`
- `uv run alembic upgrade head`

Environment note for this repo:

- `.venv/bin/python` is currently Python `3.12.x`
- `uv` may not be on the shell `PATH` in every session
- if `uv` is not found, use `/Users/jialinliu/Library/Python/3.9/bin/uv` from the repo root
- `.venv/bin/uvicorn` is available after `uv sync`

Do not introduce `poetry`, `pip-tools`, or ad hoc `requirements.txt` workflows unless explicitly requested.

### 2. Read the backend docs before making structural changes

These files are the current source of truth:

- `docs/ARCHITECTURE_DESIGN.md`
- `docs/DB_SCHEMA_DESIGN.md`
- `docs/API_CONTRACT.md`
- `docs/BACKEND_IMPLEMENTATION_DESIGN.md`
- `docs/BACKEND_STEP_BY_STEP_TODO.md`
- `docs/AI_SYSTEM_DESIGN.md`

If a code change alters one of these contracts, update the relevant doc in the same task.

### 3. Keep AI orchestration controlled

The backend AI system must follow these rules:

- deterministic preprocessing first
- read-only tool calls only
- structured output for every run type
- service-layer persistence outside the graph

If a workflow needs multi-step agentic control, implement it with `LangGraph`.

Do not add free-form agent frameworks that hide control flow or make tool execution hard to inspect.

### 4. Preserve the service boundaries

Do not put business orchestration directly inside:

- API route handlers
- SQLAlchemy models
- provider client adapters

Keep business logic in service/domain/ai orchestration layers.

### 5. Generate companion pseudocode files for Python code

Whenever you create or significantly modify a Python code file, also create or update a companion `.pcode` file in the same directory.

Examples:

- `app/main.py` -> `app/main.py.pcode`
- `app/services/ai_run_service.py` -> `app/services/ai_run_service.py.pcode`

The `.pcode` file should:

- keep exact function/class names
- summarize standard boilerplate briefly
- describe project-specific logic step by step

Do not create `.pcode` files for Markdown, JSON, or migration artifacts unless explicitly requested.

## Backend Design Constraints

## Data and storage

- PostgreSQL stores structured metadata and indexes.
- Long AI outputs, session transcripts, calibration summaries, and benchmark artifacts live in object storage.
- Full champion/item/rune catalogs are loaded from versioned JSON, not normalized into PostgreSQL tables.

## Versioning

- `data_version` is the main backend version key.
- It is not the same thing as Riot patch version.
- Patch version is optional metadata only.

## Sessions

- Logged-in users can persist sessions.
- Anonymous users can use the product, but persistence happens only after claim/save.
- Session transcript is stored as one object per session.

## Caching

- Strong cache only applies to structured requests without free text.
- Free-text requests may use reference cache, but should not directly return strong-cache payloads.
- Cache keys must follow the canonical hash rules in `docs/DB_SCHEMA_DESIGN.md` and `docs/AI_SYSTEM_DESIGN.md`.

## Leaderboard

- Only `evaluate_build` runs can update leaderboard entries.
- Only these scopes are eligible:
  - own champion + no enemy champion
  - own champion + exactly one enemy champion

## AI and tools

- Tool calls are read-only and bounded.
- Do not expose arbitrary SQL, file reads, or object-storage reads to the model.
- Inject baseline/calibration/session-memory context from the service layer before the graph starts.

## Recommended Commands

From the backend repo root:

```bash
uv sync
uv run uvicorn app.main:app --reload
uv run pytest
uv run ruff check .
uv run alembic upgrade head
```

If `uv` is not on `PATH` in the current shell:

```bash
/Users/jialinliu/Library/Python/3.9/bin/uv sync
/Users/jialinliu/Library/Python/3.9/bin/uv run pytest
```

## When editing key areas

### If you edit database models or migrations

- check `docs/DB_SCHEMA_DESIGN.md`
- keep Alembic migrations aligned
- verify indexes and uniqueness constraints still match the documented query patterns

### If you edit API schemas or routes

- check `docs/API_CONTRACT.md`
- keep request/response shapes stable
- do not silently change SSE event names

### If you edit AI orchestration

- check `docs/AI_SYSTEM_DESIGN.md`
- preserve tool boundaries
- preserve structured output contracts
- prefer `LangGraph` for complex multi-step flows

### If you edit project structure or service boundaries

- check `docs/BACKEND_IMPLEMENTATION_DESIGN.md`
- update docs if module ownership changes

## Default implementation order

If no narrower instruction is given, prefer implementing in this order:

1. config/logging/errors
2. DB models and migrations
3. game data loading and catalog APIs
4. auth and session APIs
5. AI run pipeline
6. SSE
7. cache
8. leaderboard
9. admin jobs
10. baseline/calibration/benchmark workflows
