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

## CI: Docs workflow

[docs.yml](../../.github/workflows/docs.yml) runs Claude Code (`claude -p`, model `claude-sonnet-5-5`, max 100 turns) with the prompt in [docs.md](../../.github/prompts/docs.md). It installs Node 22 and `@anthropic-ai/claude-code`, and authenticates with `ANTHROPIC_API_KEY` or, if that is empty, `CLAUDE_CODE_OAUTH_TOKEN`.

| Trigger | Mode | What happens |
|---|---|---|
| Pull request opened, updated, reopened or marked ready | `pr` | Updates the docs the PR's code changes affect, writes `docs/dev/changes/<date>-pr<number>.md`, commits to the PR branch |
| Monday 06:00 UTC, or manual run | `audit` | Checks every maintained doc against the branch's code, fills stub docs, opens or updates the PR `docs/audit-<branch>` |

- Skipped for draft PRs, Dependabot PRs and PRs from forks (no secrets), and for PRs that only change docs.
- Claude may only edit the maintained docs (`DOC_PATHS` in the workflow); a step reverts anything else before the commit.
- The docs commit is pushed with `GITHUB_TOKEN`, so it does not trigger other workflows. If status checks become required on PRs, push with a GitHub App token instead, or the checks will not run on the docs commit.
- One run per PR at a time; a new push cancels the running one.
