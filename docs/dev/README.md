# Development docs

How the code works now, and what changed recently. Claude keeps these up to date with the [Docs workflow](../../.github/workflows/docs.yml): on every pull request it updates the docs the change affects, writes a change entry (`changes/<date>-pr<number>.md`) and commits to the PR branch, so docs merge together with the code. Every Monday it also audits all docs against `main` and opens a PR with the fixes. Its instructions are in [.github/prompts/docs.md](../../.github/prompts/docs.md).

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

<!-- Newest first, at most 20. One line each: - YYYY-MM-DD [#PR title](changes/file.md): summary -->

- 2026-11-20 [#64 Edit lecture notes like a Notion page; one current version per lecture](changes/2026-11-20-pr64.md): Plate notes editor; a save renders without the model as an `edit` run; a lecture's links always show its newest published notes; `api.md`, `data.md`, `web.md` written.
- 2026-11-19 [#61 web: override katex and minimatch to patched versions](changes/2026-11-19-pr61.md): npm `overrides` in `web/package.json` pull `katex` to the root 0.19.1 and `minimatch` to `^11.0.9` under `@ts-morph/common`; closes two Dependabot alerts.
- 2026-11-19 [#57 Fix the deploy: Python 3.12 image, OIDC subject for the deploy role](changes/2026-11-19-pr57.md): API image back to `python:3.12-slim` (Dependabot ignores Python minor/major); deploy role trusts the immutable OIDC subject and the `Production` environment.
- 2026-11-18 [#54 Langfuse: cost, per-user and per-session tracking](changes/2026-11-18-pr54.md): every model call is traced with the teacher as user, the course as session, and usage and OpenRouter cost; PDFs are never sent; `worker.md` written.
- 2026-11-18 [#51 Docs bot: maintain all project docs on every PR](changes/2026-11-18-pr51.md): the Docs workflow replaces Dev docs; it commits doc updates to the PR branch and audits weekly; runs on its own docs commit are skipped; `operations.md` written.
- 2026-11-18 [#50 Check in the project Claude Code skills](changes/2026-11-18-1a9c191.md): `.claude/skills` (`shadcn`, `kse-notes-taker`) is now tracked; `.gitignore` ignores only personal `.claude` files.
- 2026-11-17 [Bump pypdf to 7.1.0](changes/2026-11-17-5bc633c.md): major bump of `pypdf` (6.19.0 to 7.1.0) in `api/uv.lock`; no code changes.
- 2026-11-17 [Bump API dependencies](changes/2026-11-17-a7c1e6a.md): Dependabot group update in `api/uv.lock` (fastapi, langchain, deepagents, ruff and others); no code changes.
- 2026-11-17 [Fix web security advisories in lockfile](changes/2026-11-17-3095b49.md): `npm audit fix` on `web/package-lock.json` only; no code changes.
- 2026-11-17 [Skip Claude review on Dependabot PRs](changes/2026-11-17-2586b7a.md): `claude-review` skips `dependabot[bot]`; `@types/node` kept on Node 24 majors.
- 2026-11-17 [Bump GitHub Actions versions](changes/2026-11-17-1b95a5a.md): checkout and setup-node v7, create-pull-request v8; workflows only.
- 2026-11-17 [Bump API Docker base image to Python 3.15](changes/2026-11-17-1f07f5f.md): `api/Dockerfile` now uses `python:3.15-slim`.
- 2026-11-17 [Add Dependabot version updates](changes/2026-11-17-cea3829.md): `.github/dependabot.yml` for uv, npm, Docker and Actions.
- 2026-11-17 [Add security policy](changes/2026-11-17-6dfe72a.md): adds `SECURITY.md`; docs only.
- 2026-11-16 [Remove remaining Render references](changes/2026-11-16-a197736.md): comment and doc wording only; backend is on AWS EC2.
- 2026-11-16 [Merge of autonomous-course-create into main](changes/2026-11-16-c5e408d.md): merge only; the `deploy.sh` SSM change is in the entry below.
- 2026-11-16 [deploy.sh refreshes .env from SSM](changes/2026-11-16-9d88192.md): `deploy.sh` writes `.env` from SecureString `/kse-notes/env` on every deploy.
- 2026-11-15 [Dev docs workflow merged to main, README logo on white](changes/2026-11-15-126bdf9.md): workflow, prompt and `docs/dev/` landed on `main`; logo background is white.
- 2026-11-15 [Dev docs workflow runs the Claude Code CLI directly](changes/2026-11-15-84bc5d6.md): replaced claude-code-action, which rejects push events, with `claude -p`.

All entries: [changes/](changes/).
