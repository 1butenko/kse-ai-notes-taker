# KSE AI Notes Taker

A dashboard for KSE lecturers to collect their course materials in one place and turn them into AI-generated notes.

Lecturers can:

- **import a course from Moodle** (teaching.kse.org.ua) by its course ID; the syllabus is filled in automatically
- upload the course **syllabus** by hand
- upload **reading materials** (papers, book chapters, slides)

The project is a plain monorepo:

```
api/   FastAPI backend (Python 3.12, uv)
web/   Next.js frontend (App Router, TypeScript, Tailwind, shadcn/ui)
```

## Requirements

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) with Docker Compose v2
- A Moodle web service token from teaching.kse.org.ua for the bot account the API uses

To run without Docker you also need:

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node.js 20.9+ and npm

## Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/1butenko/kse-ai-notes-taker.git
   cd kse-ai-notes-taker
   ```

2. Create your environment file and fill in `MOODLE_TOKEN`:

   ```bash
   cp .env.example .env
   ```

   | Variable       | Required | Example                        | Purpose                                  |
   |----------------|----------|--------------------------------|------------------------------------------|
   | `API_PORT`     | no       | `8000`                         | Host port for the API; the web app calls `http://localhost:$API_PORT` |
   | `MOODLE_URL`   | yes      | `https://teaching.kse.org.ua`  | Moodle site the API talks to             |
   | `MOODLE_TOKEN` | yes      |                                | Web service token of the Moodle bot account |
   | `OPENROUTER_API_KEY` | no |                              | Enables syllabus transcription via [OpenRouter](https://openrouter.ai) |
   | `OPENROUTER_MODEL` | no  | `google/gemini-3.1-flash-lite` | Model used for transcription           |

   The API reads these from the root `.env` (compose passes it to the container). It refuses to start if `MOODLE_URL` or `MOODLE_TOKEN` is missing. Never commit `.env`.

3. Build and start everything (this also adds the Langfuse secrets to `.env`, see [Tracing](#tracing-with-langfuse)):

   ```bash
   make up
   ```

4. Open the app:

   - Web: http://localhost:3000
   - API: http://localhost:8000 (interactive docs at http://localhost:8000/docs)
   - Langfuse: http://localhost:3001 (log in with `LANGFUSE_INIT_USER_EMAIL` / `LANGFUSE_INIT_USER_PASSWORD` from `.env`)

Both services mount their source code, so code changes reload automatically. Changes to `.env` need a restart: `docker compose up -d api`. After adding npm packages, rebuild the web container with `docker compose up -d --build -V web`.

### Running without Docker

Run the API from `api/`; it picks up the root `.env` automatically.

```bash
cd api && uv sync && uv run uvicorn app.main:app --reload --port 8000
```

```bash
cd web && npm install && npm run dev
```

## Moodle

The API talks to Moodle's REST web service (`{MOODLE_URL}/webservice/rest/server.php`) using the bot token from `.env`.

### Endpoints

| Endpoint                  | Moodle function                     | What it does                                   |
|---------------------------|-------------------------------------|------------------------------------------------|
| `GET /courses/{course_id}`| `core_course_get_courses_by_field`  | Returns one course by ID, e.g. `GET /courses/4510` |
| `GET /courses/{course_id}/contents` | `core_course_get_contents` | Returns the course sections with their modules (files, links, assignments, quizzes) |
| `POST /courses/connect`   | `core_webservice_get_site_info`     | Checks a token passed in the body (`{"token": "..."}`) and reports the account, Moodle version, whether file downloads are enabled and which required functions are missing |

Both `GET` endpoints also print what they receive (the course, then its sections and modules) to the API log: `make logs`.

### Importing a course in the UI

1. Open the course in Moodle and copy the number after `id=` in the URL, e.g. `course/view.php?id=4510`.
2. Click **Import from Moodle** in the sidebar, enter the ID and press **Import**.
3. The web app calls `GET /courses/{course_id}`, then `GET /courses/{course_id}/contents`.

The **Syllabus** card is then filled with every Moodle file whose activity name or file name contains "Syllabus" or "Силабус" (any letter case). Each one shows its Moodle name, file name, size and a **Moodle** badge, with a link to open it in Moodle. The ✕ button hides it from the card only. Links, assignments and quizzes are not treated as syllabus files.

The imported course is kept in the page only, so a refresh clears it. Files are listed, not downloaded yet.

### Errors

- `401 Invalid Moodle token`: the token is wrong
- `404 Course not found`: Moodle returned no course for that ID (it doesn't exist, or the bot can't see it)
- `502 Moodle error: <code>`: Moodle rejected the request, e.g. `wsaccessusernologin` when the bot user has the "No login" authentication method
- `502 Moodle is unreachable`: network or HTTP error talking to Moodle

### Bot account setup

The Moodle user behind the token must:

- use an authentication method that allows web services (for example "Web services authentication"), not "No login"
- not be suspended
- be able to see the courses you want to read
- belong to a web service that includes `core_course_get_courses_by_field` and `core_course_get_contents`, with file downloads enabled

### Adding a Moodle function

1. Add a model and a method to `MoodleClient` in `api/app/moodle.py` that calls `self.call(token, "<wsfunction>", **params)`.
2. Add the function name to `REQUIRED_FUNCTIONS` in `api/app/routers/courses.py`, so `/courses/connect` reports it when the service doesn't include it.
3. Expose it from a router, wrapping the call in `with moodle_errors():`.
4. Test it with the `mock_moodle` fixture in `api/tests/test_courses.py`.
5. To use it in the web app, add a typed function next to `getCourse` in `web/src/lib/api.ts`.

### Where things live in the web app

| File | Purpose |
|------|---------|
| `web/src/lib/api.ts` | API calls and the `Course` / `Section` / `Module` types |
| `web/src/lib/moodle-files.ts` | Picks syllabus files out of the course contents (`findSyllabusFiles`) |
| `web/src/components/dashboard/moodle-course-context.tsx` | Shares the imported course between the sidebar dialog and the cards |
| `web/src/components/dashboard/moodle-import-dialog.tsx` | The **Import from Moodle** dialog |
| `web/src/components/dashboard/file-upload-card.tsx` | Upload card used by Syllabus and Reading materials; shows Moodle files and local uploads |
| `web/src/components/dashboard/syllabus-plan.tsx` | **Syllabus plan** cards: Transcribe / Re-run, Use as course plan |
| `web/src/components/dashboard/course-plan.tsx` | The course plan: sessions with their files, Unassigned |
| `web/src/components/dashboard/add-material-dialog.tsx` | **Add material**: upload or choose an existing file |
| `web/src/components/dashboard/mapping-parts.tsx` | **Books** panel and proposal rows (approve, edit pages, reject) |
| `web/src/components/dashboard/file-viewer.tsx` | The in-app file viewer modal (`useFileViewer`) |

## Syllabus transcription

Every saved syllabus of the course gets a card under **Syllabus plan**. **Transcribe** sends the file to the model and shows the session plan (weeks or lectures with topics and required and optional readings) and the course-wide learning materials. `→ #n` on a reading means the model matched it to item *n* of the course materials.

- PDFs go to the model as files (OpenRouter's `native` PDF engine). DOCX is converted to HTML with `mammoth` first. Other formats are rejected.
- The result is saved next to the source as `<file>.transcript.json`, with the file's sha256 hash. Transcribing again returns the saved result, unless the file has changed or you press **Re-run** (`?force=true`).
- Citations are kept verbatim in the syllabus language. Readings not marked optional are listed as required.

| Endpoint | What it does |
|----------|--------------|
| `POST /syllabus/transcribe` | Body `{"path": "<course>/syllabus/<file>"}` (the `path` returned by `/uploads`); `?force=true` re-runs |
| `GET /syllabus/transcript?path=...` | Returns the saved transcript, `404` if there is none |
| `DELETE /syllabus?path=...` | Deletes the syllabus file and its transcript (`204`). If it was the course plan, files attached to its sessions move to Unassigned |

Errors: `400` path outside uploads or not a syllabus, `404` file missing, `413` over 20 MB, `415` not PDF/DOCX, `422` no text in the DOCX, `502` model request failed or returned an invalid transcript, `503` no `OPENROUTER_API_KEY`, `504` model timed out (120 s).

The schema lives in `api/app/syllabus.py` (Pydantic models, sent as a strict JSON schema). The OpenRouter client is `api/app/worker/openrouter.py`; tests replace it with the `mock_openrouter` fixture.

## Course plan and session materials

The first syllabus you transcribe for a course becomes its **course plan** (badge on the card). The 🗑 button on a card deletes that syllabus after a confirmation. Another transcribed syllabus can take over with **Use as course plan**. Each session of the plan has two lists:

- **From syllabus**: the required and optional readings the syllabus cites.
- **Files**: materials you attached. **Add material** uploads new files (saved as the course's reading materials, any type) or picks existing ones. One file can be attached to several sessions. ✕ detaches it from that session only; the file stays in storage.

The plan is stored in `uploads/<course>/plan.json` (`<course>` is the Moodle course ID, or `local`). Sessions have stable ids. When the plan's syllabus is re-transcribed, each new session takes over the files of the old session with the same label, or else the same number. Files of sessions that no longer exist go to **Unassigned** and are never deleted.

After a refresh the page re-imports the last opened Moodle course (remembered in the browser) and loads its saved files and plan.

| Endpoint | What it does |
|----------|--------------|
| `GET /uploads/{course}` | Lists the course's saved `syllabus` and `reading` files |
| `GET /plans/{course}` | The plan: primary syllabus, its transcript, sessions with attached files, unassigned files |
| `PUT /plans/{course}/primary` | Body `{"path"}`: use another transcribed syllabus as the plan (`409` if not transcribed) |
| `POST /plans/{course}/sessions/{id}/files` | Body `{"path"}`: attach a reading file of this course |
| `DELETE /plans/{course}/sessions/{id}/files?path=` | Detach a file from the session |
| `DELETE /plans/{course}/unassigned?path=` | Dismiss a file from Unassigned |

## Mapping materials to book chapters

Upload the course books as PDF reading materials, then press **Map materials** on the course plan. The app matches the syllabus's course materials to the uploaded PDFs (one AI call) and, for every session reading that cites chapters or pages, proposes an excerpt of the book.

- **Books** lists each course material with the file it was matched to; change a match with the dropdown (marked "set by you" and kept on later runs). Materials that sessions cite but nobody uploaded are listed under **Not uploaded**.
- Each proposal shows where its pages came from: **from bookmarks** (the PDF's own chapter outline), **from citation pages** (e.g. "p. 12-15", converted with the PDF's page labels or a detected page offset), **AI-estimated** (read from the printed table of contents, for PDFs without bookmarks) or **entered by you**. **Approve all exact** approves only the first two kinds.
- Edit the PDF page range if needed, check it with **Open**, then **Approve**: the pages are cut into `uploads/<course>/excerpts/<session>/` and appear in the session's Files with an **Excerpt** badge. ✕ on an excerpt deletes it and puts the proposal back for review. **Reject** hides a proposal; **Map materials again** never overwrites approved or rejected ones.
- Files, excerpts and proposals open in an in-app viewer (PDFs inline, other types as a download).

A book's outline, page labels and offset are cached in `uploads/<course>/index/<book>.json`, keyed by the file's hash. Pipeline code: `api/app/mapping.py` (matching, page ranges) and `api/app/books.py` (index, page conversion, cutting).

| Endpoint | What it does |
|----------|--------------|
| `POST /plans/{course}/map` | Run the mapping; returns the plan with `books` and per-session `proposals` |
| `PUT /plans/{course}/books/{material}` | Body `{"file": "<course>/reading/x.pdf" \| null}`: set a book match |
| `POST /plans/{course}/proposals/{id}/approve` | Optional body `{"pdf_start", "pdf_end"}`; cuts the excerpt |
| `POST /plans/{course}/proposals/approve-all` | Approves proposals from bookmarks or citation pages |
| `POST /plans/{course}/proposals/{id}/reject` / `reopen` | Reject, or undo a rejection |
| `GET /files?path=...` | Serves a syllabus, reading file or excerpt inline |

## Worker

The API never calls a model. `POST /syllabus/transcribe` and `POST /plans/{course}/map` validate the request, then forward it to the `worker` container (`api/app/worker/`, same image as the API, run with `uvicorn app.worker.main:app`), which owns OpenRouter and Langfuse and is not published to the host. The API keeps the plan, transcripts and Moodle; both containers share the `uploads` volume, so the worker reads syllabi and books and caches book indexes there.

| Worker endpoint | Called by | Does |
| --- | --- | --- |
| `POST /transcribe` | `POST /syllabus/transcribe` | Extracts the reading plan from a stored syllabus |
| `POST /map` | `POST /plans/{course}/map` | Matches materials to books and locates the cited pages |
| `GET /health` | compose healthcheck | |

The request and response shapes are in `api/app/worker_contract.py`; the API side is `WorkerClient` in `api/app/worker_client.py` (`WORKER_URL`, default `http://localhost:8001`). Worker errors pass through with their status (`422`, `502`, `503`, `504`); an unreachable worker is `502`, a slow one `504`. `OPENROUTER_*` and `LANGFUSE_*` are read by the worker only. Tests run the worker in-process over ASGI.

## Tracing with Langfuse

Every model call is traced to a self-hosted [Langfuse](https://langfuse.com) v4 that runs in Docker next to the app (`langfuse.compose.yaml`, included by `compose.yaml`: web, worker, Postgres, ClickHouse, Redis, MinIO). `make langfuse-env` adds any missing `LANGFUSE_*` keys and secrets to `.env` with random values; on first start Langfuse creates the `KSE` organization, the `kse-ai-notes-taker` project with those API keys, and the admin user. Tracing is off when `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` are empty, and always off in tests.

Each request that calls the model is one trace; a course's traces share the session `course-<id>`:

```
transcribe-syllabus          span: syllabus in, counts of sessions/materials/readings out
└─ extract-reading-plan      generation
map-materials                span: materials and book files in, book matches and proposals out
├─ match-books               generation
└─ map-book (one per book)   span: citations in, page proposals out
   ├─ read-book-toc          generation, only for PDFs without bookmarks
   ├─ locate-reading-pages   generation
   └─ read-page-offset       generation, only when printed pages need an offset
```

Generations record the model OpenRouter served, the full prompt (PDFs are attached as viewable files), token usage and OpenRouter's reported cost, and are marked `ERROR` when the call fails or the answer doesn't validate. Code: `api/app/worker/tracing.py` and `ask()` in `api/app/worker/llm.py`. Keep observation names stable: Langfuse dashboards and evaluators filter by them.

The browser and the worker container both reach MinIO as `http://minio.localhost:9090` (`*.localhost` resolves to your machine), so uploaded PDFs open in the Langfuse UI. The Langfuse Agent Skill for Claude Code is listed in `skills-lock.json`; restore it with `npx skills experimental_install`.

## Development

```bash
make test   # API tests (use test values from api/tests/conftest.py, not your .env)
# Live checks against real syllabi/books in test_sullabys/ (git-ignored; calls OpenRouter):
# cd api && LIVE=1 uv run pytest tests/test_syllabus_live.py -s
make lint   # ruff + eslint
make logs   # follow container logs
make down   # stop everything (Langfuse data stays in its kse-ai-notes-taker_langfuse_* volumes)
make langfuse  # open the Langfuse UI
```

## Production images

Each Dockerfile has a `dev` and a `prod` target:

```bash
docker build --target prod -t notes-api ./api
docker build --target prod --build-arg API_URL=https://api.example.com -t notes-web ./web
```

The web image uses Next.js `standalone` output. `API_URL` and `API_PORT` are read at build time.
