# KSE AI Notes Taker

A dashboard for KSE lecturers to turn their course materials into AI-generated notes.

The project is being rebuilt around a new notes generation engine. The previous syllabus, course plan, materials mapping and worker code was removed; the engine runs **offline** for now, with every external API call (LLM, embeddings, vector database, tracing) replaced by a local stand-in.

```
api/   FastAPI backend (Python 3.12, uv) + the generation engine in api/app/engine/
web/   Next.js frontend (App Router, TypeScript, Tailwind, shadcn/ui), app shell only
```

## Requirements

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) with Docker Compose v2

To run without Docker you also need:

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node.js 20.9+ and npm

## Installation

```bash
git clone https://github.com/1butenko/kse-ai-notes-taker.git
cd kse-ai-notes-taker
cp .env.example .env
make up
```

- Web: http://localhost:3000
- API: http://localhost:8000 (interactive docs at http://localhost:8000/docs)

No API keys are needed while the engine is offline.

### Running without Docker

```bash
cd api && uv sync && uv run uvicorn app.main:app --reload --port 8000
```

```bash
cd web && npm install && npm run dev
```

## Generation engine

`api/app/engine/` answers a question from the course books and writes the answer up as a Quarto study note.

```
question
└─ main agent (deepagents)     search_books -> /retrieved/<batch>/chunk_<n>.md
   ├─ chunk-analyst            summarizes one retrieved chunk (one task per chunk)
   └─ quarto-writer            writes the note and calls write_quarto_document
                               -> api/output/qmd/<name>.qmd
```

| File | Purpose |
|------|---------|
| `config.py` | Books and output folders, chunking, search and concurrency settings |
| `documents.py` | Loads every PDF in `api/data/books/` and splits it into chunks |
| `vectorstore.py` | Indexes the chunks (in memory for now) |
| `tools.py` | `search_books` and `write_quarto_document` (Quarto HTML header options from [HTML Basics](https://quarto.org/docs/output-formats/html-basics.html)) |
| `agent.py` | The deep agent with its `chunk-analyst` and `quarto-writer` subagents |
| `prompts.py`, `prompts/*.md` | System prompts; `{{name}}` placeholders are filled when loaded |
| `llm.py` | Offline stand-ins for the chat model and embeddings |

Run it on the books in `api/data/books/` (git-ignored):

```bash
make engine
# or: cd api && uv run python -m app.engine "What is an eigenvalue?"
```

### Offline mode

| Service | Stand-in now | Planned |
|---------|--------------|---------|
| Chat model | `OfflineChatModel`: replies with a fixed message, never calls tools | OpenRouter `openai/gpt-5.5` |
| Embeddings | `DeterministicFakeEmbedding`, 1024 dimensions | OpenRouter `voyageai/voyage-4` (1024 dimensions) |
| Vector database | `InMemoryVectorStore` | Amazon S3 Vectors |
| Prompts | Local `prompts/*.md` files | Langfuse Prompt Management |
| Tracing | none | Langfuse |

Each stand-in is created in one factory (`build_chat_model`, `build_embeddings` in `llm.py`, `build_vector_store` in `vectorstore.py`), so wiring a real service is a change in one place. Tests pass a scripted model to `build_agent(..., model=...)` to drive the full search, delegation and note-writing flow without network access.

## Development

```bash
make test    # API and engine tests, no network needed
make lint    # ruff + eslint
make engine  # run the engine on api/data/books/
make logs    # follow container logs
make down    # stop everything
```

## Production images

Each Dockerfile has a `dev` and a `prod` target:

```bash
docker build --target prod -t notes-api ./api
docker build --target prod --build-arg API_URL=https://api.example.com -t notes-web ./web
```

The web image uses Next.js `standalone` output. `API_URL` and `API_PORT` are read at build time.
