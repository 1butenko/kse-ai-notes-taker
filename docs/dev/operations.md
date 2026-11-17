# Operations

_running locally, env vars, Docker images, deployment, CI._

Not written yet. Run the **Dev docs** workflow with **bootstrap** to fill it, or it fills in as changes land.

## Deployment: secrets

On the AWS instance, `.env` comes from the SSM SecureString parameter `/kse-notes/env` (override the name with `ENV_PARAMETER`). [deploy.sh](../../scripts/aws/deploy.sh) fetches it on every run and replaces `/opt/kse-notes/.env` (mode 600) before `docker compose -f compose.prod.yaml up -d --build`. Change secrets in the parameter, then redeploy; manual edits to `.env` are overwritten.

## Docker: API image

[Dockerfile](../../api/Dockerfile) builds from `python:3.15-slim` (bumped from 3.12 by Dependabot) and copies `uv` from `ghcr.io/astral-sh/uv:0.9`. `api/pyproject.toml` still allows `>=3.12`.

## CI: Dependabot version updates

[dependabot.yml](../../.github/dependabot.yml) configures version updates. Security updates are enabled in the repository settings and open PRs regardless of this schedule.

| Ecosystem | Directory | Schedule | Grouping | Commit prefix |
|---|---|---|---|---|
| `uv` | `/api` | weekly, Monday | minor and patch in one PR (`api-minor-and-patch`) | `deps(api)` |
| `npm` | `/web` | weekly, Monday | minor and patch in one PR (`web-minor-and-patch`) | `deps(web)` |
| `docker` | `/api`, `/web` | monthly | none | `deps(docker)` |
| `github-actions` | `/` | monthly | all actions in one PR (`actions`) | `deps(actions)` |

`uv` and `npm` allow at most 5 open PRs each. Major updates for them arrive as separate PRs, except `@types/node`: its major updates are ignored so the types stay on Node 24 (the `node:24` runtime in `web/Dockerfile`). After merging a web dependency change, rebuild the web container (`docker compose up -d --build -V web`).

## CI: Claude code review

[claude-code-review.yml](../../.github/workflows/claude-code-review.yml) runs the `claude-review` job on pull requests. It is skipped for PRs opened by `dependabot[bot]`, because those runs have no repository secrets and the job would always fail.

## CI: Dev docs workflow

[dev-docs.yml](../../.github/workflows/dev-docs.yml) runs on pushes to `main` and `feature/**`. It installs Node 22 and the Claude Code CLI (`npm install -g @anthropic-ai/claude-code`) and runs `claude -p` with the prompt in [dev-docs.md](../../.github/prompts/dev-docs.md), model `claude-sonnet-5-5`, max 60 turns. Allowed tools: read/search, edit and write under `docs/dev/**`, and `git log`/`diff`/`show`. It authenticates with `ANTHROPIC_API_KEY` or, if that is empty, `CLAUDE_CODE_OAUTH_TOKEN`. It does not use `claude-code-action`, which rejects push events.
