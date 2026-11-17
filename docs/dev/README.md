# Development docs

How the code works now, and what changed recently. Claude keeps these up to date: every push to `main` or `feature/**` runs the [Dev docs workflow](../../.github/workflows/dev-docs.yml), which writes a change entry, updates the area docs it affects, and opens a PR (`dev-docs/<branch>`) into that branch. Its instructions are in [.github/prompts/dev-docs.md](../../.github/prompts/dev-docs.md).

Read this page, then the area doc for what you are changing.

## Area docs

| Doc | Covers |
|---|---|
| [api.md](api.md) | API (FastAPI): routers, Moodle client, storage, errors |
| [worker.md](worker.md) | Worker: model calls, agents, contract with the API |
| [web.md](web.md) | Web app (Next.js): pages, components, API client, state |
| [data.md](data.md) | Aurora tables, S3 and uploads layout, files on disk |
| [operations.md](operations.md) | Running locally, env vars, Docker images, deployment, CI |

## Recent changes

<!-- Newest first, at most 20. One line each: - YYYY-MM-DD [title](changes/file.md): summary -->

- 2026-11-17 [Add security policy](changes/2026-11-17-6dfe72a.md): adds `SECURITY.md`; docs only.
- 2026-11-16 [Remove remaining Render references](changes/2026-11-16-a197736.md): comment and doc wording only; backend is on AWS EC2.
- 2026-11-16 [Merge of autonomous-course-create into main](changes/2026-11-16-c5e408d.md): merge only; the `deploy.sh` SSM change is in the entry below.
- 2026-11-16 [deploy.sh refreshes .env from SSM](changes/2026-11-16-9d88192.md): `deploy.sh` writes `.env` from SecureString `/kse-notes/env` on every deploy.
- 2026-11-15 [Dev docs workflow merged to main, README logo on white](changes/2026-11-15-126bdf9.md): workflow, prompt and `docs/dev/` landed on `main`; logo background is white.
- 2026-11-15 [Dev docs workflow runs the Claude Code CLI directly](changes/2026-11-15-84bc5d6.md): replaced claude-code-action, which rejects push events, with `claude -p`.

All entries: [changes/](changes/).
