.PHONY: up down build logs test lint langfuse-env langfuse

up: langfuse-env
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

langfuse-env:
	@./scripts/langfuse-env.sh .env

langfuse:
	open http://localhost:3001
