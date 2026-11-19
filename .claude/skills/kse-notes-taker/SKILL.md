---
name: kse-notes-taker
description: Work on the KSE AI Notes Taker repo (FastAPI api + worker, Next.js web). Use when changing code, running the stack, testing, adding Moodle functions, or editing the dashboard UI in this project.
---

# KSE AI Notes Taker

Dashboard for KSE lecturers: import a course from Moodle, upload syllabus and readings, generate AI notes per lecture.

## Layout

| Path | What |
|------|------|
| `api/app/` | FastAPI backend; routers in `routers/`, Moodle client in `moodle.py`, notes logic in `note*.py`, `note_taker/` |
| `api/app/worker/` | Worker service: owns OpenRouter, every model call and PDF render. The api never calls a model itself |
| `api/tests/` | pytest suite |
| `web/src/app/` | Next.js App Router pages (`(dashboard)` group; a lecture's notes at `lectures/[course]/[session]/visual`) |
| `web/src/components/ui/` | shadcn components (style `base-nova`, Base UI) |
| `web/src/components/dashboard/` | App components (header, cards, Moodle dialogs) |
| `web/src/lib/api.ts` | Typed API client |
| `docs/note-taker/` | Orchestrator and Moodle subagent design |

## Commands

- Start all: `make up`; logs: `make logs`; stop: `make down`
- API tests: `cd api && uv run pytest`
- Lint: `make lint` (ruff for api, eslint for web)
- Web only: `cd web && npm run dev`
- Add npm packages, then rebuild web: `docker compose up -d --build -V web`
- `.env` changes need recreate: `docker compose up -d --force-recreate api worker`
- DB tables: `make db-init` (needs AWS credentials, `aws login`)
- Deploy: merging to `main` deploys the backend to EC2 after CI passes (`.github/workflows/deploy.yml`); roll back by running that workflow with an older `ref`. See `docs/dev/operations.md`.

## Conventions

- UI: shadcn components only when one exists (see `CLAUDE.md`); load the `shadcn` skill first.
- Next.js has breaking changes: read `web/node_modules/next/dist/docs/` before writing Next.js code.
- Adding a Moodle function: client method in `moodle.py`, name in `REQUIRED_FUNCTIONS` (`routers/courses.py`), router wrapped in `moodle_errors()`, test with `mock_moodle`, typed call in `web/src/lib/api.ts`.
- Keep model calls in the worker; the api talks to it via `worker_client.py`.
- After a web change, check it in the running container (rebuild if needed) rather than assuming.
- Never commit `.env` or real syllabi (`test_sullabys/`).
