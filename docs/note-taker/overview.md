# AI Note Taker: overview

The AI Note Taker is a [deep agent](https://docs.langchain.com/oss/python/deepagents/overview) that turns a Moodle course into study notes. It is a **main agent (the orchestrator)** that plans the job and delegates each step to a **subagent** with a narrow role and its own tools.

It lives in [`api/app/note_taker/`](../../api/app/note_taker/) and is separate from the older offline engine in `api/app/engine/`.

| Agent | Role | Status | Doc |
|-------|------|--------|-----|
| Orchestrator (`ai-note-taker`) | Plans the job, delegates, reviews, reports | Built | [orchestrator.md](orchestrator.md) |
| `moodle` subagent | Finds the relevant course files in Moodle and stores them in S3 | Built | [moodle-subagent.md](moodle-subagent.md) |
| Lecture-notes agent (`lecture-notes-writer` + `reviewer`) | Writes one lecture's visual Quarto page from its readings; started from the lecture page, not from the orchestrator | Built | [lecture-notes.md](lecture-notes.md) |

## Current state

Today the agent gathers materials end to end: it lists a Moodle course, picks the study material, stores it in S3 and records it in PostgreSQL. It then reports what it fetched and skipped, and says that note generation is not wired yet. The orchestrator prompt already describes the whole job, so adding the writers later adds a step instead of changing the flow.

What does not exist yet:
- The note-writing subagents.
- A CLI (`python -m app.note_taker`). The agent is started from the web app through the API, or from Python with `build_note_taker(course_id, moodle_course_id)`.
- Fetching the targets of external `url` modules.

## From the web app to the dashboard

```
New course dialog (name, Moodle link or id, optional focus)
  -> POST /courses                    creates the course, stores moodle_course_id
  -> POST /courses/{id}/sync          starts a run in the background (202), row in sync_runs
       sync.execute_run -> build_note_taker -> orchestrator -> task("moodle") -> S3 + materials
  -> /courses/{id}  (dashboard)       polls GET /courses/{id} every 3 s while the run is running
```

- **API** ([`api/app/courses.py`](../../api/app/courses.py), [`note_taker/sync.py`](../../api/app/note_taker/sync.py)): `GET /courses/{id}` returns the course, its topics with their materials (each with a temporary S3 download link) and the latest run. A second run for the same course is refused with 409 while one is running (a run counts as stuck after 30 minutes).
- **Topics** are the Moodle sections. The `moodle` subagent saves them to `course_topics` when it lists the course, and each material records its section, so the dashboard fills in as the run progresses.
- **Run status** is `running`, `succeeded` (with the agent's report) or `failed` (with the error). A failure is stored on the run, never raised.
- **Web** ([`web/src/components/courses/`](../../web/src/components/courses/)): `create-course-dialog.tsx` is the input, `course-dashboard.tsx` is the dashboard. The browser reaches the API through the `/api/*` rewrite.
- **Limits:** the run lives in the API process, so an API restart mid-run leaves the row `running` until it goes stale. The web flow never uses approval mode.
- Run `make db-init` to create the new tables and columns (`course_topics`, `sync_runs`, `courses.moodle_course_id`, section columns on `materials`).

## Architecture

```
request: "Make notes for course <uuid> (Moodle <id>), focus: <optional>"
   │
   ▼
┌───────────────────────────────────────────────┐
│ Orchestrator  (create_deep_agent, "ai-note-taker")
│   tools: write_todos, ls/read_file/write_file…, task
│   no tools of its own
└──────┬────────────────────────────────────────┘
       │ task("moodle", one complete instruction)
       ▼
┌───────────────────────────────────────────────┐
│ moodle subagent
│   list_course_contents · preview_module · fetch_materials
└──────┬─────────────────┬──────────────────┬───┘
       │                 │                  │
       ▼                 ▼                  ▼
  Moodle web        S3 bucket          PostgreSQL
  services          courses/<id>/      materials table
  (token)           materials/…

Shared virtual filesystem (StateBackend), visible to both agents:
  /moodle/catalog.json        full course catalog
  /materials/manifest.json    fetched / skipped / failed, with reasons
```

### Design rules

- **The orchestrator never touches Moodle.** It can only reach Moodle through the `moodle` subagent, so every Moodle permission is in one place.
- **Subagents are stateless.** They see only the instruction the orchestrator sends, so that instruction must be complete: course, focus topic and rules.
- **Scope is fixed in code.** `course_id` and `moodle_course_id` are bound into the tools when the agent is built. The model never passes them, so it cannot read or write another course.
- **Big payloads stay out of messages.** The catalog and the manifest are files in the virtual filesystem, and tools return only short outlines. File bytes never enter agent state: they stream from Moodle to S3 and only S3 keys come back.
- **Moodle content is data, not instructions.** Both prompts tell the model to ignore instructions found in course names, pages or files.

### Components

| Part | Where |
|------|-------|
| Agent factory `build_note_taker` | `agent.py` |
| Chat model (OpenRouter) | `llm.py` |
| Prompt loaders | `prompts.py`, `prompts/*.md` |
| Subagent specs, one module each | `subagents/` |
| Moodle client, catalog, tools, materials store | `moodle/` |

`build_note_taker` accepts `moodle_client`, `materials` and `upload` so tests can inject fakes. By default they are the real Moodle site, PostgreSQL and S3.

## Human approval

When `approval=True`, the `moodle` subagent's `fetch_materials` tool pauses for a human before downloading, and the main agent gets a `MemorySaver` checkpointer so it can pause and resume. A run then needs a `thread_id`. The setting `NOTE_TAKER_APPROVAL` is meant to drive this from the CLI. The build side is covered by a test. The resume flow (approve, edit, reject) is not tested yet and will arrive with the CLI.

## Prompts

Prompts are managed in Langfuse and the Markdown files in the repo are a synced fallback:

| Langfuse prompt | File |
|-----------------|------|
| `note-taker/orchestrator` | `prompts/orchestrator.md` |
| `note-taker/moodle` | `prompts/moodle.md` |
| `note-taker/lecture-notes/writer`, `/reviewer`, `/skills-system`, `/request` | `lecture_notes/prompts/*.md` |
| Skills tagged `lecture-notes` (Langfuse Skills) | `lecture_notes/skills/<name>/SKILL.md` |

Edit them in the Langfuse UI, then run `make prompts-pull` and commit the files. See the prompts section of the [README](../../README.md).

## Configuration

| Setting | Purpose |
|---------|---------|
| `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` | Chat model, shared by all agents unless a subagent sets its own |
| `MOODLE_URL`, `MOODLE_TOKEN` | Moodle site and web-service token |
| `NOTE_TAKER_APPROVAL` | Ask a human before the `moodle` subagent downloads |
| `S3_BUCKET`, `DB_*` | Storage, see [storage.md](../storage.md) |
| `LANGFUSE_*` | Prompt and skill management; `LANGFUSE_TRACING` traces lecture-notes runs |

## Tests

`api/tests/test_note_taker.py` covers the orchestrator. `api/tests/test_moodle_subagent.py` covers the Moodle tools and a full run through `task("moodle")` with a scripted model, a fake Moodle client and in-memory storage. Nothing has been run against a real Moodle site or model yet.
