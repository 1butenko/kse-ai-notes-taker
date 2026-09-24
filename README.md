# KSE AI Notes Taker

Plain monorepo: one directory per component, Docker Compose for local dev.

```
api/   FastAPI (Python 3.12, uv)
web/   Next.js (App Router, TypeScript, Tailwind)
```

## Run everything

```bash
docker compose up --build   # or: make up
```

- Web: http://localhost:3000
- API: http://localhost:8000 (OpenAPI docs at `/docs`)

Both services bind-mount their source, so edits hot-reload.

## How web talks to api

- Server components call `API_URL` directly (`http://api:8000` inside compose).
- Browser code calls `/api/*`; Next.js rewrites it to FastAPI, so there's no CORS in the normal path.

## Running without Docker

```bash
cd api && uv sync && uv run uvicorn app.main:app --reload
cd web && npm install && npm run dev
```

## Production images

Each Dockerfile has a `dev` and a `prod` target:

```bash
docker build --target prod -t notes-api ./api
docker build --target prod --build-arg API_URL=https://api.example.com -t notes-web ./web
```

The web image uses Next.js `standalone` output. `API_URL` is a build arg because rewrites are fixed at build time.
