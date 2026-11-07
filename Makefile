.PHONY: up down build logs test lint db-init prompts-push prompts-pull

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

test:
	cd api && uv run pytest

lint:
	cd api && uv run ruff check . && uv run ruff format --check .
	cd web && npm run lint

# AI Note Taker: create or update its tables in Aurora (needs DB_HOST and AWS credentials).
db-init:
	cd api && uv run python -m app.manage init-db

prompts-push:
	cd api && uv run python -m app.prompts push

prompts-pull:
	cd api && uv run python -m app.prompts pull
