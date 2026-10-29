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

3. Build and start everything (this also adds the Langfuse secrets to `.env`, see [Tracing](#tracing-with-langfuse)):

   ```bash
   make up
   ```

4. Open the app:

   - Web: http://localhost:3000
   - API: http://localhost:8000 (interactive docs at http://localhost:8000/docs)
   - Langfuse: http://localhost:3001 (log in with `LANGFUSE_INIT_USER_EMAIL` / `LANGFUSE_INIT_USER_PASSWORD` from `.env`)

Both services mount their source code, so code changes reload automatically. Changes to `.env` only reach a container when it is recreated (`docker compose restart` keeps the old values): `docker compose up -d --force-recreate api worker`. `OPENROUTER_*` and `LANGFUSE_*` are read by the worker. After adding npm packages, rebuild the web container with `docker compose up -d --build -V web`.

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

## Notes generation

Once sessions have materials (excerpts or attached files), `POST /plans/{course}/notes` generates the course notes. The pipeline plans globally, writes each topic from all of its readings, verifies each topic, then composes the document:

1. **Inputs**: every session material is read as text (excerpts from their book's page range, PDFs page by page, DOCX/Markdown/text whole). The text is cut into chunks with stable ids (`<file hash>-p<page>-<n>`) and page metadata, then indexed for retrieval (BM25). Page text is cached in `uploads/<course>/text/`. Scanned PDFs have no text and are reported as warnings, and so is every page of an excerpt with almost no text (under 40 characters: a scan or a blank page). PDF text loses typeset matrices (their entries run together), math set in TeX fonts (`≠` comes out as `=`) and everything on scanned pages. So when an excerpt is approved, the worker has the vision model transcribe those pages of it to Markdown with LaTeX, in the background (`POST /books/transcribe` on the worker). The transcripts are cached once per page in `uploads/<course>/text/<hash>.vision.json`, keyed by model and prompt, and notes use them in place of the PDF text. A run reports the pages it had to take from the PDF text. For excerpts approved before this existed, run `uv run python -m app.worker.vision <course>` once (in Docker: `docker compose exec worker python -m app.worker.vision <course>`).
2. **Planning**: the planner builds sections → topics with objectives, success criteria, prerequisites, sources and shared notation. The coverage checker reviews it against a rubric (syllabus coverage, duplicates, granularity, evidence, ordering). The plan is revised with that feedback until no blocking issues remain, for up to `NOTES_PLAN_ROUNDS` rounds.
3. **Topics** (up to `NOTES_CONCURRENCY` at a time): collect candidate chunks → the selector keeps the useful ones and gives each a role (definition, theorem, proof, example, …). A topic whose own readings are at most 24 chunks gets them all, in page order, and the selector only gives them roles; longer readings are searched with the topic's key terms, which the planner writes in the topic's language and in the readings' language when that differs. A few chunks of other readings are searched and selected either way → the writer synthesizes structured blocks with citations → the verifier checks them against the evidence. Failing drafts are revised with the verifier's issues for up to `NOTES_REVISION_ROUNDS` revisions. Verification moves to the escalation model when the verifier asks for it (hard proofs, conflicting sources) or when errors survive a revision.
4. **Composition**: notes are collected in plan order. A consistency pass makes targeted edits to individual blocks to unify notation, remove repetition and add cross-references, and citations are kept. The format writer renders `notes.qmd` deterministically, and Quarto typesets it to `notes.pdf` with Typst (DejaVu fonts, Ukrainian or English labels).
5. **Topic PDFs**: every written topic (verified or unresolved) is also typeset on its own as `topics/<id>/note.pdf`: the topic title, its section and course as subtitle, its blocks and only the sources it cites, numbered from 1. Up to 4 render at a time; a topic that fails to render is a warning, not a failed run.

| Stage | Default model (OpenRouter) | Reasoning | Env var |
|-------|----------------------------|-----------|---------|
| Planner | `openai/gpt-6.1-sol` | medium | `NOTES_PLANNER_MODEL` |
| Coverage checker | `openai/gpt-6.1-sol` | high | `NOTES_PLANNER_MODEL` |
| Evidence selector | `openai/gpt-6-luna` | low | `NOTES_SELECTOR_MODEL` |
| Topic synthesizer | `google/gemini-3.7-flash` | medium | `NOTES_WRITER_MODEL` |
| Topic verifier | `openai/gpt-6-luna` | high | `NOTES_VERIFIER_MODEL` |
| Escalated verifier | `openai/gpt-6.1-sol` | high | `NOTES_ESCALATION_MODEL` |
| Page transcription (vision) | `google/gemini-3.7-flash` | low | `NOTES_VISION_MODEL` (empty turns it off) |
| Global consistency | `google/gemini-3.7-flash` | medium | `NOTES_WRITER_MODEL` |

Writing and verification use different model families, so each draft gets a second opinion. Coverage issues of kind `weak_evidence` (a topic no uploaded material covers) never block the plan: no revision can fix them, so they become run warnings instead.

A run takes minutes, so the worker answers `202` at once and keeps working. Poll `GET /plans/{course}/notes/{run}` until its `status` is `done` or `failed`. Every stage stores its artifacts in `uploads/<course>/notes/<run>/`:

```
run.json                 status, stage, progress, warnings, event log, models
inputs.json              sources and mapped chunks
plan/draft-N.json        planner output per round
plan/review-N.json       coverage review per round
plan.json                final course plan
topics/<id>/evidence.json        selected chunks with roles, relevance, excerpt; gaps
topics/<id>/draft-N.json         each draft version
topics/<id>/verification-N.json  check results, issues, the model that checked
topics/<id>/note.json            the completed topic note
topics/<id>/note.qmd, note.pdf   the topic as its own document and PDF
notes.json               final structured notes with provenance
notes.qmd, notes.pdf     the Quarto document and its PDF (quarto.log on failure)
```

`POST /plans/{course}/notes` with `{"resume": "<run>"}` continues a failed run that was never published. A run that is `done` is refused with `409`: its notes are revision 0 and may already be edited (see [Editing and publishing notes](#editing-and-publishing-notes)), so generate again in a new run. It reuses the plan and every finished topic, retries failed topics, then composes again. Resume requires the original ordered attachments, source bytes, syllabus context and language; changes or missing provenance return `409` with a new-run instruction and preserve all cached files. New runs freeze extracted inputs and context in `inputs.json` and `provenance.json`; older published notes remain readable, while an unpublished legacy run without that provenance must be regenerated in a new run. A topic whose model call fails is marked `failed` without stopping the run, and a topic still failing verification is kept as `unresolved`, flagged in rendered formats with its open issues unless a teacher approves that saved topic for students (see [Teacher approval](#teacher-approval)). A final verifier that still requests escalation also stays unresolved with its reason visible.

| Endpoint | What it does |
|----------|--------------|
| `POST /plans/{course}/notes` | Start a run (`202`), or resume one with `{"resume": "<run>"}`. `409` without a transcribed plan, without session materials, while a run is going, or when resuming a `done` run |
| `GET /plans/{course}/notes` | The course's runs, newest first |
| `GET /plans/{course}/notes/{run}` | The run's status, plus the structured notes once it is done |
| `GET /plans/{course}/notes/{run}/pdf` / `qmd` | The typeset PDF or its Quarto source |
| `GET /plans/{course}/notes/{run}/topics/{topic}/pdf` | One topic's PDF (`404` if the topic has none). The run view lists them in `topic_pdfs` |

### Preview links

`/preview/<course>/<run>` in the web app shows the full notes PDF with every topic listed next to it; `/preview/<course>/<run>/<topic>` shows one topic's PDF. The page has no dashboard around it, so the link can be shared as is (**Copy link**), and it carries the notes or topic title for link previews. The **Lecture notes** card links to it (**Preview page**) and opens each topic's PDF in the viewer (**Open**).

Langfuse trace: `generate-notes` → `plan-course` (`draft-course-plan`, `check-coverage`), one `generate-topic` per topic (`select-evidence`, `synthesize-topic`, `verify-topic`, `verify-topic-escalated`, `revise-topic`), `compose-notes` (`harmonize-notes`). Code: `api/app/notes.py` (artifacts) and `api/app/worker/` (`sources.py`, `planning.py`, `topics.py`, `composition.py`, `render.py`, `notes.py`, `models.py`).

The worker image (`worker-dev` / `worker-prod` targets) adds Quarto, whose bundled Typst makes the PDF, so no LaTeX is needed. Its build renders a sample document, so a broken Quarto or font setup fails the build instead of the first run. Without Quarto (e.g. running the worker outside Docker) the run still finishes with `notes.qmd` and a warning instead of a PDF.

## Lecture notes

The web app writes one note per lecture, only when the lecturer asks (spec: [docs/superpowers/specs/2026-10-27-lecture-notes.md](docs/superpowers/specs/2026-10-27-lecture-notes.md)). After the lectures are approved, their readings are matched and shown on **Readings per lecture**; **Approve readings** (stored as `readings_approved_at` in `course.json`, cleared when the syllabus is read again, its lectures edited or replaced) opens the notes section. Each lecture row opens its note, or its lecture page (`/lectures/<course>/<session>`) with **Generate note**, its readings and a drop zone for files of that lecture only.

A lecture run is an ordinary notes run whose plan and transcript are cut down to one session before admission (`scope_to_session` in `api/app/plan.py`), so everything in [Notes generation](#notes-generation) and [Editing and publishing notes](#editing-and-publishing-notes) applies inside it. The run records `session_id`, and its `materials` is that lecture's readings fingerprint (excerpt pages included); the plan view gives each session's current one, which is how "Readings changed since this note was written" is detected. Inside the run the lecture is session `S0`, so map runs to lectures by `run.session_id`, never by `topic_sessions`. The planner gets one lecture and returns one section of 1 to 4 topics.

- **Queue.** The worker writes one job per course at a time. `POST /plans/{course}/sessions/{session}/notes` and Generate all go through the same per-course queue (mirrored in `<course>/queue.json`); each lecture reads the current plan from disk when it starts. Generate all queues every lecture without a note that has readings, in syllabus order, continues a stopped run when its readings are unchanged, and reports lectures without readings as skipped.
- **Stop.** Cancels the run being written (Quarto subprocesses included), marks it `failed` with "Stopped; resume to continue" and empties the queue. Resume reuses the plan and every finished section. A worker restart fails the active run and drops the queue with a warning on that run.
- **Regenerate and retry.** Regenerate writes a new run; the note shown stays the newest finished run, so the old one moves to Previous versions with its edits and approvals. A finished run with failed sections can't be resumed (its notes are published), so **Retry failed section** starts a new run seeded with the old run's frozen inputs, plan and finished sections, and writes only the failed ones; if the readings changed since, it writes the whole lecture.
- **Lecture-only files** are stored under `<course>/lecture/<session>/`, attached to that session and flagged `lecture_only`. They are not course readings, so matching, the readings list and other lectures never see them; detaching one deletes it.
- **Course notation** (`<course>/notation.json`) is seeded by the first finished lecture run. Each lecture run freezes it at admission, plans against it as binding (its meaning wins on conflict) and appends only new symbols and terms when done. `GET /course-info/{course}/notation` shows it.

| Endpoint | What it does |
|----------|--------------|
| `POST /plans/{course}/sessions/{session}/notes` | Write one lecture's note (`202`); `{"resume": "<run>"}` continues its stopped run, `{"retry": "<run>"}` rewrites a finished run's failed sections in a new run. `404` for an unknown lecture, `409` without readings or while the course has a job |
| `POST /plans/{course}/notes/queue` | Generate all; returns the queue and the lectures skipped for having no readings. `409` when no lecture needs a note |
| `GET /plans/{course}/notes/queue` | The run being written and the lectures waiting |
| `POST /plans/{course}/notes/stop` | Stop the run being written and clear the queue |
| `POST /plans/{course}/sessions/{session}/lecture-files` | Upload files for one lecture only (multipart `files`) |
| `POST` / `DELETE /course-info/{course}/readings-approval` | Approve the readings per lecture, or clear the approval |
| `GET /course-info/{course}/notation` | The course notation sheet (view-only) |

Whole-course runs from before lecture notes stay readable under **Previous generations** and never appear in the lecture list; `POST /plans/{course}/notes` still starts and resumes them (the notes E2E suite uses it).

## Editing and publishing notes

A finished run (`status: done`) can be read as HTML and PDF, edited topic by topic, restored to an earlier text, exported to Word and refined with AI suggestions. Editing, restoring and rendering never call a model; only AI suggestions and the manual recheck need OpenRouter. The architectural decisions behind this are recorded in [docs/superpowers/specs/2026-10-23-quarto-notes-decisions.md](docs/superpowers/specs/2026-10-23-quarto-notes-decisions.md).

This workflow was developed on `feature/quarto-notes` from `notes-generation-engine` at `2829b7b`. The structured `NotesDocument` is the source of truth; QMD, HTML, PDF, DOCX and the course book are generated from a saved revision.

### Revisions

The generated `notes.json` is **revision 0** and is never rewritten. Every save creates a new immutable snapshot next to it, and `head.json` names the current revision:

```
uploads/<course>/notes/<run>/
  notes.json                       revision 0, as generated
  head.json                        {"revision": N}: the current revision
  assets/<sha256>.png|jpg          uploaded figures (immutable)
  revisions/000000/                frozen copy of revision 0 (created by the first edit)
  revisions/NNNNNN/document.json   the whole document at that revision
  revisions/NNNNNN/revision.json   parent, origin (manual, restore, ai, verification, teacher approval/revocation), changed topics and decision audit
  revisions/NNNNNN/jobs/           render jobs of the revision
  revisions/NNNNNN/artifacts/      manifest.json and one folder per render job
  suggestions/, verification-jobs/ AI suggestions and manual rechecks (not part of any snapshot)
```

Only the current revision and its parent chain count as history. A save carries the `base_revision` it was made from: if another tab saved first, it gets `409` and nothing is written. Only completed runs can be edited, and a published run cannot be resumed (start a new run instead).

### Editing, history and restore

Open `/preview/<course>/<run>/<topic>` and use the **Edit** tab: change a block's kind, title, text (Markdown with LaTeX) and citations (chosen from the topic's own evidence), add, delete or reorder blocks, then **Save**. The **History** tab compares revisions block by block and **Restore** copies an earlier text into a **new** revision (history is never rewritten).

- An unsaved draft is kept in the browser tab (`sessionStorage`), survives a 409 and offers to transfer it onto the newer revision. The preview shows the draft only after it is saved and rendered.
- A topic whose text changed (by hand, restore or AI) becomes **Unresolved** with "Verification outdated": the old `verified` status is never carried over to different text. Topics you did not touch keep their current status. Use **Verify this topic again** (below) to check the new text.
- **Insert image** uploads a PNG or JPEG (up to 10 MiB and 20 megapixels) and adds `![caption](assets/<sha256>.png){#fig-label}` to the draft. Uploading alone changes no revision; the file is published when a saved revision references it. Only images uploaded this way can be used.
- Notes generated before the language was recorded may have none: pick Ukrainian or English in the editor before saving; it is never guessed. Rendering such a revision fails with that instruction until you do.

### Teacher approval

In a saved, nonempty topic's **Edit** tab, review the AI findings, enter your name and an optional comment, then choose **Approve for students**. The name is provided by the reviewer; this app does not authenticate teacher identities. Save or discard a draft first. **Revoke approval** records a later decision. The **History** tab shows each action, reviewer, server time and comment in an immutable revision; the AI status and findings stay visible and unchanged. Approval and revocation use no model.

Approval omits only the automatic AI-verification caution from that topic in student HTML, PDF, Word and course-book chapters. Authored warning callouts and notices for failed or empty topics remain. Approval belongs to the exact saved text, citations, evidence, relevant sources and figures, language and heading context. Changing those clears it; changing another topic or recording a verification result with identical text and evidence keeps it. Restore copies authored text only and cannot bring back an old approval. If a render fails, the decision remains saved and the previous files retain their own revision labels. Word and course books are prepared on demand for the chosen revision, so historical files use the decision recorded in that revision.

### Render jobs and retry

Every save, restore and applied suggestion queues a render job for the new revision (HTML and PDF, full notes and each written topic). The preview shows both the **text revision** and the revision of each shown file; a file that is older than the text is labelled "Older artifact" and is never presented as current. Files are served per revision and never fall back to another one:

| Endpoint | What it does |
|----------|--------------|
| `GET /plans/{course}/notes/{run}/revisions` / `.../revisions/{n}` | History (newest first) / one revision with its document |
| `PATCH /plans/{course}/notes/{run}/topics/{topic}` | Body `{"base_revision", "blocks", "language"?}`: save a topic. Empty block `id` adds a block. `409` stale base or run not done, `422` unknown block, evidence or figure |
| `POST .../topics/{topic}/approval` | Body `{"base_revision", "action": "approve" \| "revoke", "reviewer", "comment"?}`: record a teacher decision and queue HTML/PDF. `409` on a stale base; `422` for invalid or ineligible decisions |
| `POST .../revisions/{n}/restore` | Body `{"base_revision"}`: restore revision *n*'s text as a new revision |
| `POST .../revisions/{n}/render` | Body `{"formats": ["html", "pdf", "docx", "book"]}`: queue a render job (`202`), also to retry. The requested formats can be a subset |
| `GET .../render-jobs/{job}` | `queued`, `running`, `done` or `failed`, with `errors` |
| `GET .../revisions/{n}/artifacts/{html\|pdf\|docx}` | The revision's full notes; `.../revisions/{n}/topics/{topic}/artifacts/{kind}` for one topic. `404` if that revision has no such file |
| `POST .../assets`, `GET .../assets/{id}` | Upload and download a figure |
| `GET .../revisions/{n}/book/` | Open the search-enabled course book for exactly revision *n*; linked chapters and assets stay under that revision |

The older `GET .../{html,pdf,qmd,docx}` URLs still work: they serve the newest ready file and name its revision in the `X-Notes-Revision` header (`qmd` is always revision 0).

A failed render never touches the saved text or an earlier file. If Quarto is missing or breaks, the save still succeeds, the job ends as `failed` with the Quarto error, the preview keeps showing the previous files with their own revision and offers **Retry render**; once Quarto works again, retry creates the files without regenerating anything. A successful output is kept when only another format fails, and a failed retry keeps the previous file of the same kind. If the worker restarts mid-render, the job is marked `failed` and can be retried. Run one worker per `uploads` directory (the worker refuses to start otherwise). `QUARTO_CONCURRENCY` (default 4) caps the Quarto processes of all generation and render jobs together.

PDF and DOCX files link to other topics through `PUBLIC_API_URL`, pointing at the HTML of the same revision.

### Word export

**Prepare Word** in the Preview tab queues a DOCX render of the revision on screen; **Download Word** appears when the file is that exact revision. History can prepare and download Word for a selected earlier revision too. Word is created on demand only, with a linked contents list in place of Word's table-of-contents field (which stays empty until updated), native editable equations and the bibliography. The contents has no page numbers. The control DOCX was rendered in math-enabled LibreOffice, including parenthesized superscripts; large callouts can leave sparse pages there. Microsoft Word itself has not been tested. A Google Docs import preserved superscripts but flattened matrix rows and sometimes separated a callout title from its body.

### Course book and complete workflow

On the full-notes Preview tab, choose **Prepare course book** to build a searchable Quarto book from the current saved revision. The **Course book** tab opens it after the job finishes. Each chapter, search index and link belongs to that revision; an older book is labelled with its number after a later edit. A failed attempt leaves the previous ready book available and offers **Retry course book**. The publication serves only the book's approved output files, with sandboxed HTML; it does not include uploaded readings or AI working files. The standalone full PDF remains available separately. Books use the same citation and reference validation as other formats: unknown labels, duplicate labels and foreign evidence fail the job. Failed topics retain status pages; a reference to a known persisted target in such a topic links to its status page, while a missing label with no known owner fails validation. Chapter filenames are prefixed independently of stable topic IDs, including legacy IDs named `index` or `references`.

For a typical review: open a generated run, read HTML or PDF, edit a topic and save, wait for its new render job, then compare revisions in **History** or restore an older text as a new revision. Request an AI suggestion in **Edit**, inspect its diff and fresh source check, then reject or apply it; use **Verify this topic again** after manual changes. Prepare Word for the current or a historical revision, and prepare the course book when the text is ready. Each view labels the text and displayed artifact revisions. If Quarto fails, use the render retry after fixing it; the saved revision and last successful files remain available. Without OpenRouter, manual edits, history, render retries, Word and book still work, while suggestions and manual rechecks return `503`.

### AI suggestions and manual recheck

These need `OPENROUTER_API_KEY` on the worker. Without it they answer `503` and everything above keeps working.

- In the **Edit** tab, select blocks (none selects the whole topic), pick a preset or describe the change, and request a suggestion. Nothing changes yet: the review shows the text and source diff and a fresh verification of exactly the proposed text. The model only returns replacements and insertions; the server assigns block IDs, keeps every unselected block in place and accepts only citations from the topic's own evidence.
- **Apply** creates a new revision (and a render job) only if the notes are still at the revision the suggestion was made for, and applies it once. **Reject** changes nothing. A stale suggestion cannot be applied.
- The topic becomes `verified` only when the check of exactly the applied text finds no major issue, the verifier is not unsure, and the topic has no standing evidence gap (those are listed as blocking). Otherwise it stays Unresolved with the reasons shown.
- **Verify this topic again** (`POST .../topics/{topic}/verify` with `{"base_revision"}`, then poll `GET .../verification-jobs/{id}`) checks the saved text of one topic against its sources without rewriting it. A clean result is recorded as a new revision with origin `verification`; if the notes changed while the check ran, the result is reported as a conflict and the newer text is not certified.

### Running the notes E2E

The browser suite starts its own stack (mock OpenRouter, worker, API and web on ports 8124-8126 and 3124) with a temporary uploads directory and real Quarto, so it needs no keys or production data:

```bash
cd web && npm run test:e2e:notes
```

Setup, the environment variables (`NOTES_E2E_QUARTO_BIN`, `TYPST_FONT_PATHS`, `NOTES_E2E_CHROME`, port and keep/hold options) and what each test covers are in [web/e2e/notes/README.md](web/e2e/notes/README.md).

## Worker

The API never calls a model. `POST /syllabus/transcribe` and `POST /plans/{course}/map` validate the request, then forward it to the `worker` container (`api/app/worker/`, same image as the API, run with `uvicorn app.worker.main:app`), which owns OpenRouter and Langfuse and is not published to the host. The API keeps the plan, transcripts and Moodle; both containers share the `uploads` volume, so the worker reads syllabi and books and caches book indexes there.

| Worker endpoint | Called by | Does |
| --- | --- | --- |
| `POST /transcribe` | `POST /syllabus/transcribe` | Extracts the reading plan from a stored syllabus |
| `POST /map` | `POST /plans/{course}/map` | Matches materials to books and locates the cited pages |
| `POST /notes` | `POST /plans/{course}/notes` | Starts or resumes a notes run in the background (`202`) |
| `POST /notes/revise`, `/notes/restore` | `PATCH .../topics/{topic}`, `POST .../revisions/{n}/restore` | Saves a topic or restores an earlier revision as a new revision, without a model |
| `POST /notes/render` | `POST .../revisions/{n}/render` | Queues an HTML/PDF/DOCX render job for a saved revision (`202`) |
| `POST /notes/suggestions`, `/apply`, `/reject` | `POST .../suggestions...` | Prepares, applies or rejects an AI suggestion |
| `POST /notes/verify` | `POST .../topics/{topic}/verify` | Re-checks one saved topic against its sources (`202`) |
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
