.PHONY: up down build logs test lint

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
