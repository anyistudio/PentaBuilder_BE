.PHONY: run install db-upgrade

run:
	uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

install:
	uv sync

db-upgrade:
	uv run alembic upgrade head
