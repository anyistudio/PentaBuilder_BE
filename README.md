# PentaBuilder Backend

## Quickstart

```bash
/Users/jialinliu/Library/Python/3.9/bin/uv sync --extra dev
/Users/jialinliu/Library/Python/3.9/bin/uv run uvicorn app.main:app --reload
```

Health check:

```bash
curl http://127.0.0.1:8000/healthz
```

## Common Commands

```bash
/Users/jialinliu/Library/Python/3.9/bin/uv run pytest
/Users/jialinliu/Library/Python/3.9/bin/uv run ruff check .
/Users/jialinliu/Library/Python/3.9/bin/uv run alembic upgrade head
/Users/jialinliu/Library/Python/3.9/bin/uv run python scripts/generate_localization_assets.py
```

If `uv` is already on your shell `PATH`, use plain `uv ...`.

## Environment Files

- local/dev: `.env.dev.example`
- production: `.env.prod.example`
- generic reference: `.env.example`

## Manual Setup Docs

- Clerk: `docs/CLERK_SETUP.md`
- Railway deploy: `docs/DEPLOYMENT_GUIDE.md`
