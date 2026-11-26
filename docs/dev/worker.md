# Worker

The worker is a second FastAPI service (`api/app/worker`) and the only place that calls a model. The API never talks to OpenRouter: it sends the worker a request from `worker_contract.py` through `WorkerClient`. Locally it is the `worker` Compose service; in production it runs next to the API on the EC2 host. It owns the uploads directory (a lock file allows one worker per directory).

## Layout

| File | What it holds |
|---|---|
| [main.py](../../api/app/worker/main.py) | The FastAPI app, its endpoints, startup (lock, mark interrupted runs failed) |
| [config.py](../../api/app/worker/config.py) | `WorkerSettings`: model names, OpenRouter, Quarto, lecture-notes limits |
| [openrouter.py](../../api/app/worker/openrouter.py) | `OpenRouterClient.complete_json` (strict JSON schema, `usage: {include: true}`), `Completion`, client openers |
| [llm.py](../../api/app/worker/llm.py) | `ask()`: structured call mapped to 502/504, traced as a generation; PDF helpers |
| [models.py](../../api/app/worker/models.py) | `ModelSpec`: model and reasoning effort for a call |
| [transcribe.py](../../api/app/worker/transcribe.py) | Syllabus PDF/DOCX to model messages; `drop_bad_refs` |
| [mapping.py](../../api/app/worker/mapping.py), [book_reading.py](../../api/app/worker/book_reading.py) | Match syllabus materials to books, read tables of contents and page offsets |
| [vision.py](../../api/app/worker/vision.py), [sources.py](../../api/app/worker/sources.py) | Page text and vision transcripts of book pages, cached per page |
| [tracing.py](../../api/app/tracing.py) | Langfuse helpers shared by every model call (outside `worker/`) |
| [worker_contract.py](../../api/app/worker_contract.py), [worker_client.py](../../api/app/worker_client.py) | Request/response models and the API's client |

## How it works

| Endpoint | Does | Trace (Langfuse) |
|---|---|---|
| `POST /transcribe` | Reads an upload, asks for a `SyllabusExtraction` | `transcribe-syllabus` → generation `extract-reading-plan` |
| `POST /map` | `run_mapping`: books to materials, ranges, page offsets | `map-materials` → `match-books`, `read-book-toc`, `locate-reading-pages`, `read-page-offset` |
| `POST /books/transcribe` (202) | Background vision transcription of garbled pages | `transcribe-pages` → `transcribe-page` |
| `POST /note-taker/runs` (202) | Background `sync.execute_run` (orchestrator + Moodle subagent); result goes to `sync_runs` | `prepare-course` |
| `POST /lecture-notes/runs` (202) | Background `runs.execute_run`; 429 above `lecture_notes_concurrency`; result goes to `lecture_note_runs` | `lecture-notes` (writer, reviewer, motivation scout) |
| `POST /lecture-notes/edits` (202) | Background `runs.execute_edit`: renders a teacher's edit of a succeeded run (`LectureNotesEditRequest`: `run_id`, `parent_id`, `course`, `body`, `assets`) and publishes it, without the model; the outcome goes to the run's row | none |
| `POST /lecture-notes/cancel` | Sets the run's cancel event | none |
| `GET /health` | `{status, environment}` | none |

Endpoints return 503 when `OPENROUTER_API_KEY` is missing, and 400 for a bad course key (`local` or digits).

## Interfaces

- **Contract:** every request that calls a model extends `worker_contract.Traced`, which has an optional `user_id`. `get_worker_client` depends on the signed-in principal, and `WorkerClient.call` fills `user_id` with the principal's `id` when it is empty. No route had to change.
- **Env vars:** see `WorkerSettings`: `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `NOTES_VISION_MODEL`, `NOTE_TAKER_MODEL`, `LECTURE_NOTES_MODEL`, `LECTURE_NOTES_REVIEWER_MODEL`, `LECTURE_NOTES_*` limits, `LECTURE_NOTES_WEB`, `LECTURE_NOTES_SEARCH_MODEL`, `LECTURE_NOTES_MAX_SEARCHES`, `LECTURE_NOTES_MAX_IMAGES` (the motivation scout's web search and images; only that subagent has web tools, in [web.py](../../api/app/note_taker/lecture_notes/web.py)), `QUARTO_*`, `API_URL`, `API_AUTH_SECRET`, `UPLOADS_DIR`, `ENVIRONMENT`.

## Tracing

All of it lives in [tracing.py](../../api/app/tracing.py); see "Tracing" in [overview.md](../note-taker/overview.md).

- One trace per request: `traced(name, user_id, session_id, ...)`. `user_id` is the teacher's `users.id`, or `worker` if none was sent. `session_id` is `course-<key>` (`course_session`), so one course's work shows together.
- Direct calls: `ask(..., step=...)` opens a generation named `step` and `record_completion` stores the served model, usage (`usage_details`) and OpenRouter's cost (`cost_details`). Errors set the generation level to `ERROR`.
- LangChain agents (Note Taker, lecture notes) pass `tracing.callback_handler()`, which adds OpenRouter's cost that Langfuse's own handler drops.
- Attached PDFs are never traced: `without_files` reduces each `file` part to its filename before Langfuse sees it. Text prompts and answers are traced.
- The Langfuse environment is `ENVIRONMENT` (`local` in Compose, `production` in `compose.prod.yaml`). No keys, or `LANGFUSE_TRACING=false`, means no tracing.
- Background jobs are traced inside the job (after the response), and long runs call `tracing.flush()` at the end.

## Conventions and gotchas

- A new model-calling endpoint: make its request extend `Traced`, wrap the work in `traced(...)`, and call models through `ask(..., step="<name>")` or pass `callback_handler()` to the agent. Otherwise its cost and user are lost.
- Do not trace PDFs: put them in the input only as OpenRouter `file` parts so `without_files` strips them.
- Do not run two workers on one uploads directory; startup fails on the lock.
- Runs interrupted by a restart are marked failed at startup.
