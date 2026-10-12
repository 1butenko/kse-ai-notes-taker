#!/bin/sh
set -e
mkdir -p "$UPLOADS_DIR"
uvicorn app.worker.main:app --host 127.0.0.1 --port 8001 &
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-7860}"
