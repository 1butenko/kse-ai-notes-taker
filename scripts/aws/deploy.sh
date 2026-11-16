#!/bin/sh
# Deploy the backend on the EC2 host: check out a branch/tag/commit and rebuild the containers.
#   sudo /opt/kse-notes/scripts/aws/deploy.sh [ref]   (default: main)
# Run it on the instance, e.g. through SSM Session Manager or `aws ssm send-command`.
set -eu

REF="${1:-main}"
cd "$(dirname "$0")/../.."

git fetch --prune origin
if git show-ref --verify --quiet "refs/remotes/origin/$REF"; then
  git checkout -B "$REF" "origin/$REF"
else
  git checkout --detach "$REF"
fi
echo "Deploying $(git rev-parse --short HEAD) ($REF)"

docker compose -f compose.prod.yaml up -d --build --remove-orphans
docker image prune -f
docker compose -f compose.prod.yaml ps
