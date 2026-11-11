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
   | `PUBLIC_API_URL` | no | `http://localhost:8000` | Absolute API base for links inside downloaded PDF/DOCX notes; include any deployment path prefix, no credentials, query or fragment |

   The API reads these from the root `.env` (compose passes it to the container). It refuses to start if `MOODLE_URL` or `MOODLE_TOKEN` is missing. Never commit `.env`.

3. Build and start everything:

   ```bash
   make up
   ```

4. Open the app:

   - Web: http://localhost:3000
   - API: http://localhost:8000 (interactive docs at http://localhost:8000/docs)

Both services mount their source code, so code changes reload automatically. Changes to `.env` only reach a container when it is recreated (`docker compose restart` keeps the old values): `docker compose up -d --force-recreate api worker`. `OPENROUTER_*` is read by the worker. After adding npm packages, rebuild the web container with `docker compose up -d --build -V web`.

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
2. Click **From Moodle** on the **Reading materials** card, enter the ID and press **Import course**. **Change course** in the same dialog imports another one.
3. The web app calls `GET /courses/{course_id}`, then `GET /courses/{course_id}/contents`.

The **Syllabus** card is then filled with every Moodle file whose activity name or file name contains "Syllabus" or "Силабус" (any letter case). Each one shows its Moodle name, file name, size and a **Moodle** badge, with a link to open it in Moodle. The ✕ button hides it from the card only. Links, assignments and quizzes are not treated as syllabus files.

**From Moodle** on the **Reading materials** card lists the course's other files (PDF, Word, PowerPoint, text) and its links to web pages, by Moodle section. Checked items are downloaded on **Save and continue** as reading materials: files as they are, web pages (e.g. lecture slides) as Markdown text, or as a PDF when the link serves one. Links to YouTube or Vimeo are left out. Only links that belong to the course are fetched (`POST /uploads/moodle/links` with `{"course_id", "modules": [<module id>]}`); pages over 20 MB are refused.

A file saved again under the same name replaces the old one, except a book whose pages approved excerpts read: if its bytes changed, the whole save is refused with `409`, naming the file and the lectures whose excerpts use it (upload it under another name, or remove those excerpts first). Saving the same file again, e.g. a repeated Moodle import, always works.

Moodle files are downloaded when you save.

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
| `web/src/components/dashboard/moodle-course-context.tsx` | Shares the imported course between the import form and the cards |
| `web/src/components/dashboard/moodle-course-form.tsx` | The course ID form that imports a Moodle course |
| `web/src/components/dashboard/moodle-materials-dialog.tsx` | **From Moodle**: imports the course, then picks its files and web pages |
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
- Edit the PDF page range if needed, check it with **Open**, then **Approve**: the excerpt appears in the session's Files with an **Excerpt** badge. It is stored once, as the book and its page range: the session lists `<course>/excerpts/<proposal id>`, which is no file, and `GET /files` cuts those pages from the book whenever the excerpt is opened. Notes are written from the same pages of the book. ✕ on an excerpt removes it and puts the proposal back for review. **Reject** hides a proposal; **Map materials again** never overwrites approved or rejected ones.
- Courses from before this kept excerpts as cut PDFs under `uploads/<course>/excerpts/<session>/`. They still work; to drop the copies, stop the API and worker and run `uv run python -m app.excerpt_migration --dry-run`, then without `--dry-run` (in Docker: `docker compose run --rm --no-deps api python -m app.excerpt_migration`). It renames the excerpts in `plan.json` and in the runs that froze the plan, so earlier notes can still be resumed, retried and compared with the current readings, then deletes the files. Files a session uses without a proposal describing their pages are kept and listed.
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

## Notes

Each lecture's notes are written by the **lecture-notes agent**, a LangChain deep agent, from that lecture's readings. They are a Quarto page with diagrams, interactive figures, worked examples and self-checks, shown in the app. Full design: [docs/note-taker/lecture-notes.md](docs/note-taker/lecture-notes.md).

- **Writing.** On a lecture's page, **Write the notes** starts a run (`POST /lecture-notes/{course}/{session}/runs`). The worker runs the agent:
  - It reads the lecture's readings: PDF excerpts page by page, using the vision transcription where the PDF text garbles formulas, plus Markdown and Word files.
  - It writes the page with the help of its Quarto skills.
  - It renders the page with `render_notes`, which validates against an allowlist and runs `quarto render --no-execute` in a sandbox, and fixes what fails.
  - A reviewer subagent checks the page against the readings.
  - The page is published to S3. The lecture page shows the agent's progress, and **Stop** cancels the run.
- **Reading.** The lecture list shows each lecture's status: *No notes*, *Writing*, *Notes ready*, *Readings changed* or *Failed*. It links to `/lectures/<course>/<session>/visual/<run>`, which shows the page in a sandboxed iframe, along with earlier versions and a `.qmd` download. Pages are served by `GET /lecture-notes/runs/{run}/site/{path}` with a strict sandbox CSP.
- **Tracking.** Prompts and skills are managed in Langfuse (`make prompts-push` / `prompts-pull`), and each run is one Langfuse trace (`LANGFUSE_TRACING`). Each run records the prompt and skill versions it used.
- **Storage.** Runs are in Aurora (`lecture_note_runs`, created by `make db-init`) and pages are in S3 under `courses/<id>/lecture-notes/<session>/<run>/`. The worker image includes Quarto.

| Endpoint | Purpose |
|----------|---------|
| `POST /lecture-notes/{course}/{session}/runs` | Write one lecture's notes (`202`). `409` without readings or while the lecture has a run going |
| `GET /lecture-notes/{course}/runs` | Every lecture's latest run and latest published run (the lecture list) |
| `GET /lecture-notes/{course}/{session}/runs` | One lecture's runs, newest first |
| `GET /lecture-notes/runs/{run}` | Poll a run |
| `POST /lecture-notes/runs/{run}/cancel` | Stop a run |
| `GET /lecture-notes/runs/{run}/site/{path}` | The published page and its files |

## Worker

The API never calls a model. `POST /syllabus/transcribe` and `POST /plans/{course}/map` validate the request, then forward it to the `worker` container (`api/app/worker/`, same image as the API, run with `uvicorn app.worker.main:app`), which owns OpenRouter and is not published to the host. The API keeps the plan, transcripts and Moodle; both containers share the `uploads` volume, so the worker reads syllabi and books and caches book indexes there.

| Worker endpoint | Called by | Does |
| --- | --- | --- |
| `POST /transcribe` | `POST /syllabus/transcribe` | Extracts the reading plan from a stored syllabus |
| `POST /map` | `POST /plans/{course}/map` | Matches materials to books and locates the cited pages |
| `POST /books/transcribe` | approving an excerpt | Transcribes excerpt pages whose PDF text garbles formulas (`202`) |
| `POST /note-taker/runs` | `POST /agent/courses/{course}/sync` | Runs the AI Note Taker (Moodle setup) in the background (`202`) |
| `POST /lecture-notes/runs`, `/lecture-notes/cancel` | `POST /lecture-notes/...` | Runs or stops the lecture-notes agent (`202`, `429` when `LECTURE_NOTES_CONCURRENCY` runs are going) |
| `GET /health` | compose healthcheck | |

The request and response shapes are in `api/app/worker_contract.py`; the API side is `WorkerClient` in `api/app/worker_client.py` (`WORKER_URL`, default `http://localhost:8001`). Worker errors pass through with their status (`422`, `502`, `503`, `504`); an unreachable worker is `502`, a slow one `504`. `OPENROUTER_*` is read by the worker only. Tests run the worker in-process over ASGI.

## Development

```bash
make test   # API tests (use test values from api/tests/conftest.py, not your .env)
# Live checks against real syllabi/books in test_sullabys/ (git-ignored; calls OpenRouter):
# cd api && LIVE=1 uv run pytest tests/test_syllabus_live.py -s
make lint   # ruff + eslint
make logs   # follow container logs
make down   # stop everything
```

## Demo deployment (free)

The web app runs on Vercel (project `kse-notes`, root directory `web`); the API and the worker run together in one free [Render](https://render.com) web service, built from the `demo` stage of `api/Dockerfile` (`api/demo/start.sh` starts both, on `$PORT`). Vercel alone can't host the backend: notes runs take minutes in the background, need Quarto and keep files on disk.

1. In Render, **New → Blueprint**, pick this repository: `render.yaml` creates the `kse-notes-api` service (free plan, from the `notes-generation-engine` branch; change `branch` after merging). Enter the `MOODLE_TOKEN` and `OPENROUTER_API_KEY` secrets when asked.
2. The service answers at `https://kse-notes-api.onrender.com` (Render adds a suffix if the name is taken). The Vercel project's `NEXT_PUBLIC_API_URL` and `API_URL` must be that URL; `NEXT_PUBLIC_API_URL` is read at build time, so redeploy the web app after changing it.
3. CORS allows the project's Vercel domains through `CORS_ORIGIN_REGEX`; add other origins to `CORS_ORIGINS`.

The free instance has 512 MB of RAM, so the blueprint typesets one PDF at a time (`QUARTO_CONCURRENCY=1`) and writes two topics at a time (`NOTES_CONCURRENCY=2`). It sleeps after 15 minutes without requests (the first request wakes it in about a minute) and its disk is reset on every deploy or restart, so uploads and runs are lost; download what you want to keep.

With a Hugging Face PRO account, `scripts/deploy-space.sh <hf-user>/<space> [<course>/<run> ...]` deploys the same image as a Docker Space (16 GB RAM) and can copy finished runs from the local uploads volume onto it, without book text. `SPACE_DRY_RUN=1` builds the image locally instead.

## Production images

Each Dockerfile has a `dev` and a `prod` target:

```bash
docker build --target prod -t notes-api ./api
docker build --target worker-prod -t notes-worker ./api
docker build --target prod --build-arg API_URL=https://api.example.com -t notes-web ./web
```

The web image uses Next.js `standalone` output. `API_URL` and `API_PORT` are read at build time.
