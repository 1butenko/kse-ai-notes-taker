#!/usr/bin/env bash
# Upload the API and worker to a Hugging Face Docker Space.
#   scripts/deploy-space.sh <user>/<space> [<course>/<run> ...]
# Each <course>/<run> is copied from the local uploads volume and served on the Space as a demo.
set -euo pipefail

space="${1:?usage: scripts/deploy-space.sh <user>/<space> [<course>/<run> ...]}"
shift
root="$(cd "$(dirname "$0")/.." && pwd)"
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT

cp -R "$root/api/app" "$root/api/demo" "$root/api/Dockerfile" "$root/api/pyproject.toml" \
  "$root/api/uv.lock" "$stage/"
mv "$stage/demo/README.md" "$stage/README.md"
find "$stage" -name __pycache__ -prune -exec rm -rf {} +

if [ "$#" -gt 0 ]; then
  docker compose -f "$root/compose.yaml" run --rm --no-deps -T \
    -v "$stage/demo/seed:/seed" api python - "$@" < "$root/scripts/space_seed.py"
fi

if [ "${SPACE_DRY_RUN:-}" = 1 ]; then
  docker build -t notes-space "$stage"
  exit 0
fi

hf repo create "$space" --repo-type space --space_sdk docker --exist-ok
hf upload "$space" "$stage" . --repo-type space --delete "*" --commit-message "Deploy from $(git -C "$root" rev-parse --short HEAD)"
echo "Deployed: https://huggingface.co/spaces/$space"
