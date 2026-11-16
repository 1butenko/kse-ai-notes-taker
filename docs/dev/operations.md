# Operations

_running locally, env vars, Docker images, deployment, CI._

Not written yet. Run the **Dev docs** workflow with **bootstrap** to fill it, or it fills in as changes land.

## Deployment: secrets

On the AWS instance, `.env` comes from the SSM SecureString parameter `/kse-notes/env` (override the name with `ENV_PARAMETER`). [deploy.sh](../../scripts/aws/deploy.sh) fetches it on every run and replaces `/opt/kse-notes/.env` (mode 600) before `docker compose -f compose.prod.yaml up -d --build`. Change secrets in the parameter, then redeploy; manual edits to `.env` are overwritten.

## CI: Dev docs workflow

[dev-docs.yml](../../.github/workflows/dev-docs.yml) runs on pushes to `main` and `feature/**`. It installs Node 22 and the Claude Code CLI (`npm install -g @anthropic-ai/claude-code`) and runs `claude -p` with the prompt in [dev-docs.md](../../.github/prompts/dev-docs.md), model `claude-sonnet-5-5`, max 60 turns. Allowed tools: read/search, edit and write under `docs/dev/**`, and `git log`/`diff`/`show`. It authenticates with `ANTHROPIC_API_KEY` or, if that is empty, `CLAUDE_CODE_OAUTH_TOKEN`. It does not use `claude-code-action`, which rejects push events.
