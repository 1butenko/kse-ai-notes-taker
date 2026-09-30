#!/bin/sh
set -eu

env_file=${1:-.env}
touch "$env_file"
if [ -s "$env_file" ] && [ "$(tail -c1 "$env_file")" != "" ]; then
  echo >> "$env_file"
fi

add() {
  if grep -q "^$1=" "$env_file"; then
    echo "kept  $1"
  else
    printf '%s=%s\n' "$1" "$2" >> "$env_file"
    echo "added $1"
  fi
}

hex() { openssl rand -hex "$1"; }

add LANGFUSE_PUBLIC_KEY "pk-lf-$(hex 16)"
add LANGFUSE_SECRET_KEY "sk-lf-$(hex 16)"
add LANGFUSE_BASE_URL "http://localhost:3001"
add LANGFUSE_INIT_USER_EMAIL "admin@example.com"
add LANGFUSE_INIT_USER_PASSWORD "$(hex 12)"
add LANGFUSE_SALT "$(hex 32)"
add LANGFUSE_ENCRYPTION_KEY "$(hex 32)"
add LANGFUSE_NEXTAUTH_SECRET "$(hex 32)"
add LANGFUSE_POSTGRES_PASSWORD "$(hex 16)"
add LANGFUSE_CLICKHOUSE_PASSWORD "$(hex 16)"
add LANGFUSE_REDIS_PASSWORD "$(hex 16)"
add LANGFUSE_MINIO_PASSWORD "$(hex 16)"
