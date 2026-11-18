# KSE AI Notes Taker

Monorepo: `api/` (FastAPI, Python 3.12, uv; `api/app/worker` is the model-calling worker) and `web/` (Next.js App Router, TypeScript, Tailwind, shadcn/ui). Run everything with `make up` (Docker Compose). Read `README.md` first and `docs/note-taker/` for the AI Note Taker.

## Development docs

Before changing code, read `docs/dev/README.md` (area docs and recent changes), then the area doc for what you touch and the recent entries in `docs/dev/changes/`. They are written by the Dev docs GitHub workflow on every push; don't edit them by hand in feature work, the workflow updates them.

## Working here

- Use the project skill `kse-notes-taker` (`.claude/skills/kse-notes-taker`) for commands, layout and conventions.
- Web package manager is npm (`package-lock.json`); the Docker web container needs a rebuild after adding packages: `docker compose up -d --build -V web`.
- Never commit `.env`.
