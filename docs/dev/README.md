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

- 2026-11-18 [Web-only Claude guidance moved to web/CLAUDE.md](changes/2026-11-18-1367994.md): shadcn/Next.js rules now live in `web/CLAUDE.md`.
- 2026-11-16 [Claude Code GitHub workflows](changes/2026-11-16-afad6f9.md): `@claude` assistant and automatic PR review workflows merged from `main`.
- 2026-11-16 [deploy.sh refreshes .env from SSM](changes/2026-11-16-9d88192.md): `deploy.sh` writes `.env` from SecureString `/kse-notes/env` on every deploy.
- 2026-11-15 [Dev docs workflow runs the Claude Code CLI directly](changes/2026-11-15-84bc5d6.md): replaced claude-code-action, which rejects push events, with `claude -p`.

All entries: [changes/](changes/).
