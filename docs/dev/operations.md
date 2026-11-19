# Operations

How to run the project locally, what the environment variables do, how the Docker images are built, how the backend is deployed, and what CI does. Locally everything runs in Docker Compose (`api`, `worker`, `web`). In production the backend (`api` + `worker`) runs on an AWS EC2 host behind CloudFront and the web runs on Vercel.

## Layout

| File | What it holds |
|---|---|
| [Makefile](../../Makefile) | Shortcuts for compose, tests, lint, DB init and prompts sync |
| [compose.yaml](../../compose.yaml) | Local dev stack: bind-mounted sources, hot reload |
| [compose.prod.yaml](../../compose.prod.yaml) | Production backend: `api` (port 80) and `worker`, no `web` |
| [.env.example](../../.env.example) | Every env var, with comments. Copy to `.env` (never commit it) |
| [api/Dockerfile](../../api/Dockerfile) | Targets `dev`, `prod`, `worker-dev`, `worker-prod`, `demo` (see below) |
| [web/Dockerfile](../../web/Dockerfile) | Targets `dev`, `build`, `prod` (Next.js standalone) |
| [scripts/aws/deploy.sh](../../scripts/aws/deploy.sh) | Deploy on the EC2 host |
| [scripts/aws/github-deploy-role.sh](../../scripts/aws/github-deploy-role.sh) | One-time setup of the IAM role the Deploy workflow assumes |
| [scripts/deploy-space.sh](../../scripts/deploy-space.sh) | Upload API and worker to a Hugging Face Docker Space (demo) |
| [.github/workflows/](../../.github/workflows/) | `ci.yml`, `deploy.yml`, `claude-code-review.yml`, `claude.yml`, `docs.yml` |

## Running locally

| Command | What it does |
|---|---|
| `make up` | `docker compose up --build`: web on :3000, api on `${API_PORT}` (default 8000, docs at `/docs`), worker internal at `http://worker:8000` |
| `make down` / `make logs` | Stop the stack / follow logs |
| `make test` | `cd api && uv run pytest` |
| `make lint` | `ruff check` and `ruff format --check` in `api/`, `npm run lint` in `web/` |
| `make db-init` | `python -m app.manage init-db`: create or update the AI Note Taker tables in Aurora (needs `DB_HOST` and AWS credentials) |
| `make prompts-push` / `make prompts-pull` | `python -m app.prompts push` / `pull`: sync prompts with Langfuse |

- The api waits for a healthy worker (`/health`), and the web waits for a healthy api.
- `api` and `worker` share the `uploads` volume (`UPLOADS_DIR=/data/uploads`) and mount `~/.aws` for Aurora and S3 (`aws login`; set `AWS_PROFILE` for a non-default profile).
- The API reaches the worker at `WORKER_URL`, the worker reaches the API at `API_URL`. Only the worker calls models (OpenRouter).
- After adding web packages, rebuild: `docker compose up -d --build -V web`.

## Environment variables

Defined in [.env.example](../../.env.example); the real values live in `.env`.

| Group | Variables |
|---|---|
| API | `API_PORT`, `PUBLIC_API_URL` (absolute base for links in downloaded notes, including any path prefix) |
| Moodle | `MOODLE_URL`, `MOODLE_TOKEN` |
| Models | `OPENROUTER_API_KEY` (optional; without it syllabus transcription is off), `NOTE_TAKER_MODEL` |
| Sign-in | `API_AUTH_SECRET` (same value for web, api and worker), `SHARED_COURSES` (JSON list of course keys open to all teachers), `AUTH_SECRET`, `AUTH_GOOGLE_ID`, `AUTH_GOOGLE_SECRET`, `AUTH_ALLOWED_DOMAINS` |
| AWS | `AWS_REGION`, `S3_BUCKET`, `DB_HOST`, `DB_NAME` (Aurora uses IAM auth) |
| Langfuse | `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`, `LANGFUSE_TRACING` (traces every model call with user, session and cost; attached PDFs are never sent, text prompts are); `ENVIRONMENT` is the Langfuse environment (`production` in `compose.prod.yaml`) |
| Lecture notes | `LECTURE_NOTES_MODEL`, `LECTURE_NOTES_REVIEWER_MODEL`, `LECTURE_NOTES_MAX_CHARS`, `LECTURE_NOTES_MAX_RENDERS`, `LECTURE_NOTES_CONCURRENCY` |

Compose sets `ENVIRONMENT=local`, `CORS_ORIGINS`, `UPLOADS_DIR`, `WORKER_URL` and `API_URL` itself. The web container gets the sign-in variables plus `AUTH_URL` and `AUTH_TRUST_HOST` from compose.

## Deployment

Every push to `main` whose CI passes is deployed by [deploy.yml](../../.github/workflows/deploy.yml) (GitHub environment `production`):

1. It resolves the commit, then assumes the IAM role in the `production` environment variable `AWS_DEPLOY_ROLE_ARN` through GitHub OIDC (no AWS keys in GitHub). The role trusts only `repo:1butenko/kse-ai-notes-taker:environment:production` and may only run `AWS-RunShellScript` on the instance and read the result. [github-deploy-role.sh](../../scripts/aws/github-deploy-role.sh) creates it.
2. Over `aws ssm send-command` it checks out the commit in `/opt/kse-notes` and runs `deploy.sh <sha>`, waits (up to 30 minutes), prints the output and fails if the command fails.
3. It polls `https://<cloudfront>/health` until `commit` equals the deployed SHA.

Deploys run one at a time (concurrency group `deploy-production`); a newer one waits instead of cancelling. **Roll back**: Actions → Deploy → Run workflow with an older commit, tag or branch as `ref`. The `production` environment only allows the `main` branch; add required reviewers there to gate deploys.

`deploy.sh` exports `GIT_SHA` (the checked-out commit); `compose.prod.yaml` passes it to the `api`, and `/health` returns it as `commit` (empty locally).

By hand, run `sudo /opt/kse-notes/scripts/aws/deploy.sh [ref]` on the EC2 host (default ref `main`), for example through SSM Session Manager. It fetches, checks out the ref, refreshes `.env` (see below), then runs `docker compose -f compose.prod.yaml up -d --build --remove-orphans` and prunes images. Production containers restart `unless-stopped`, log to json-file (20 MB x 5) and use the instance role for AWS credentials instead of `~/.aws`. CloudFront forwards HTTPS to port 80 of the `api` container.

## Deployment: secrets

On the AWS instance, `.env` comes from the SSM SecureString parameter `/kse-notes/env` (override the name with `ENV_PARAMETER`). [deploy.sh](../../scripts/aws/deploy.sh) fetches it on every run and replaces `/opt/kse-notes/.env` (mode 600) before `docker compose -f compose.prod.yaml up -d --build`. Change secrets in the parameter, then redeploy; manual edits to `.env` are overwritten.

## Docker: API image

[Dockerfile](../../api/Dockerfile) builds from `python:3.15-slim` (bumped from 3.12 by Dependabot) and copies `uv` from `ghcr.io/astral-sh/uv:0.9`. `api/pyproject.toml` still allows `>=3.12`.

| Target | Used by |
|---|---|
| `dev`, `prod` | `api` (dev: all deps, reload; prod: no dev deps, non-root) |
| `worker-dev`, `worker-prod` | `worker`: the API image plus Quarto (typesets the notes PDF with Typst). A warm-up render at build time fails the build if Quarto or fonts are broken |
| `demo` | API and worker in one container on port 7860 (Hugging Face Space); keep it the last stage |

[web/Dockerfile](../../web/Dockerfile) builds from `node:26-alpine`.

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

[claude.yml](../../.github/workflows/claude.yml) runs Claude Code on issue and PR comments, reviews, and new or assigned issues. [claude-code-review.yml](../../.github/workflows/claude-code-review.yml) runs the `claude-review` job on pull requests. It is skipped for PRs opened by `dependabot[bot]`, because those runs have no repository secrets and the job would always fail. It is also skipped for commits pushed by `github-actions[bot]` (the Docs workflow's docs commits), because the action refuses bot actors.

## CI: Docs workflow

[docs.yml](../../.github/workflows/docs.yml) runs Claude Code (`claude -p`, model `claude-sonnet-5-5`, max 100 turns) with the prompt in [docs.md](../../.github/prompts/docs.md). It installs Node 22 and `@anthropic-ai/claude-code`, and authenticates with `ANTHROPIC_API_KEY` or, if that is empty, `CLAUDE_CODE_OAUTH_TOKEN`.

| Trigger | Mode | What happens |
|---|---|---|
| Pull request opened, updated, reopened or marked ready | `pr` | Updates the docs the PR's code changes affect, writes `docs/dev/changes/<date>-pr<number>.md`, commits to the PR branch |
| Monday 06:00 UTC, or manual run | `audit` | Checks every maintained doc against the branch's code, fills stub docs, opens or updates the PR `docs/audit-<branch>` |

- Skipped for draft PRs, Dependabot PRs and PRs from forks (no secrets), and for PRs that only change docs.
- Claude may only edit the maintained docs (`DOC_PATHS` in the workflow); a step reverts anything else before the commit.
- The docs commit (author `github-actions[bot]`) triggers the PR workflows again. `docs.yml` and `claude-code-review.yml` skip runs whose actor is `github-actions[bot]`, so it does not loop; other checks, such as CI, run on it as usual.
- One run per PR at a time; a new push cancels the running one.
