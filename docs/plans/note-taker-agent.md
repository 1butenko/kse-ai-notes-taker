# AI Note Taker Deep Agent with a `moodle` subagent

## Context
The app builds study notes from Moodle course materials. The current engine (`api/app/engine/`) is an offline, CLI-only deep agent over local PDFs, and the Moodle integration was removed in the reset (`e7c2a2f`). We are building a **new, separate main agent, the "AI Note Taker"**, without touching `app/engine`. It owns the whole job, from course materials to notes, and delegates specialized work to subagents.

The first subagent is **`moodle`**. Given a course, it lists everything, decides what is relevant for note-taking, downloads that to S3 and returns a manifest. The note-writing subagents come later and plug into the same main agent.

Decisions: files go **directly to S3** (existing `storage.py` layout), there is **optional HITL** approval before download, and the model is **OpenRouter** (`ChatOpenRouter`).

## Architecture

```
AI Note Taker  (main agent, create_deep_agent)
  role: turn a Moodle course into study notes
  built-ins: write_todos (plans the job), filesystem (StateBackend), task
  │
  ├─ subagent "moodle"          ← v1: built now
  │     tools: list_course_contents, preview_module, fetch_materials
  │     returns: summary + /materials/manifest.json (S3 keys, reasons)
  │
  └─ (later) "material-reader" / "notes-writer"
        read the manifest and S3 files, write .qmd notes to courses/<id>/notes/
```

**Main agent flow.** The input is something like "Make notes for course <uuid> (Moodle <id>), focus: <optional topic>".
1. It plans with `write_todos`, for example: gather materials, then write the notes.
2. It calls `task("moodle", …)` with one complete instruction (course, focus, rules), because subagents are stateless.
3. It reads `/materials/manifest.json` from the shared state filesystem.
4. In v1 it ends with a report: what was fetched, what was skipped and why. It states that note generation is not wired yet. The main prompt already describes the full job, so adding the writer subagents later only adds a step.

**Context hygiene.** Big payloads go to the virtual filesystem, not into messages.
- `/moodle/catalog.json` holds the full catalog. The tool returns only a compact outline.
- `/materials/manifest.json` holds the fetch results.
- Binary files never enter agent state. They are streamed Moodle → S3, and only S3 keys come back.

**Relevance.** The `moodle` subagent's LLM decides, from names, types, mimetypes, sizes, section titles and previews, guided by rules in the prompt:
- Keep: slides and PDFs, readings, pages, books and folders with documents.
- Skip: forum, quiz, attendance, feedback, choice, assignment submissions, huge videos and duplicates.
- Each choice records a one-line reason.
- If the main agent passes a focus topic, the subagent narrows its selection to the matching sections.

**HITL.** `interrupt_on={"fetch_materials": True}` on the `moodle` subagent, gated by a flag (`NOTE_TAKER_APPROVAL`). This needs a checkpointer (`MemorySaver`) and a `thread_id`. The approver sees the chosen items and their reasons and can approve, edit (prune the list) or reject.

## Tools of the `moodle` subagent
1. **`list_course_contents()`**
   - Calls `core_course_get_contents`.
   - Normalizes the result into flat items: `module_id, section, modname, name, url, files[{filename, fileurl, mimetype, filesize, timemodified}]`.
   - Writes the full JSON to `/moodle/catalog.json` with `backend.upload_files`, using the same pattern as `make_search_books_tool` in `api/app/engine/tools.py`.
   - Returns about one line per module.
2. **`preview_module(module_id, max_chars=2000)`**
   - Returns plain text for `page`, `label` and `book` content and for section summaries.
   - Returns the target and title for `url` modules, and metadata only for files.
3. **`fetch_materials(items: list[{module_id, filename?, reason}])`**
   - Resolves each item against the stored catalog. The agent can't invent URLs.
   - Streams each file from Moodle with the token and uploads it to S3 at `storage.material_key(course_id, file_id, name)`.
   - Skips a file if one with the same `source_url` and `timemodified` is already stored.
   - Upserts a `materials` row for each file and writes `/materials/manifest.json`.
   - Returns `{fetched, skipped, failed}`.
   - **HITL gate.**
4. *(Later)* `fetch_external_link(url)` for `url` modules, reusing `links.py` from the `main` branch.

`course_id` and `moodle_course_id` are bound into the tools by closure when the agent is built, not passed by the LLM. This scopes everything the agent can touch to one course.

## Files

New package `api/app/note_taker/`:
- `agent.py`: `build_note_taker(course_id, moodle_course_id, *, model=None, approval=False)`.
  - Calls `create_deep_agent(model, system_prompt=note_taker_prompt, backend=StateBackend(), subagents=[moodle_subagent(...)], checkpointer=MemorySaver() if approval else None)`.
  - The main agent gets no Moodle tools of its own. It can only reach Moodle through `task`.
- `subagents/moodle.py`: `build_moodle_subagent(...) -> dict` with `name`, `description`, `system_prompt`, `tools` and `interrupt_on`. Each later subagent gets its own module under `subagents/`.
- `moodle/client.py`: port `MoodleClient`, `MoodleError` and the Pydantic models from `git show e7c2a2f^:api/app/moodle.py`. Drop the FastAPI dependency.
  - Add `iter_download(token, fileurl)`, which streams bytes and raises an error when it gets JSON back.
  - Add `get_page_html(fileurl)`.
- `moodle/catalog.py`: `normalize_contents(sections) -> list[CatalogItem]`, an HTML-to-text helper and the skip-list of modnames.
- `moodle/tools.py`: `make_moodle_tools(client, token, backend, s3, conn, course_id, moodle_course_id)`, which returns the three `@tool(parse_docstring=True)` tools.
- `prompts/orchestrator.md`, `prompts/moodle.md`, plus a `prompts.py` loader in the `{{var}}` style of `app/engine/prompts.py`.
- `llm.py`: `build_chat_model()` → `ChatOpenRouter(model=settings.openrouter_model)`.
- `__main__.py`: CLI `python -m app.note_taker <course_uuid> <moodle_course_id> [--focus "..."] [--approve]`.
  - Runs the agent with a `thread_id`.
  - On `__interrupt__`, prints the proposed items and resumes with approve, reject or an edited list.
  - Prints the final report.

Edits:
- `api/app/storage.py`: add `upload_stream(key, fileobj, content_type)` using `s3.upload_fileobj`.
- `api/app/schema.sql`: add a `materials` table:
  - Columns: `id uuid`, `course_id` FK, `moodle_module_id`, `name`, `mimetype`, `size`, `s3_key`, `source_url`, `moodle_timemodified`, `reason`, `fetched_at`.
  - Unique key on `(course_id, source_url, moodle_timemodified)`.
- `api/app/config.py`: add `moodle_url`, `moodle_token`, `openrouter_api_key`, `openrouter_model` and `note_taker_approval`.
- `.env.example`, `api/pyproject.toml`: add the OpenRouter LangChain integration, `httpx` and `beautifulsoup4`.
- `Makefile`: add a `note-taker` target.

Reused code: `storage.material_key`, `storage.safe_file_name`, `storage.s3_client`, `db.connect` / `db.transaction`, and the prompt loader pattern and backend-write pattern from `app/engine`.

## Verification
- **Unit tests** (`api/tests/test_note_taker.py`):
  - Fake Moodle client returns fixture `core_course_get_contents` JSON. Stub S3. Use a `ScriptedModel` like the one in `tests/test_engine.py`.
  - Assert that the main agent's `task(moodle)` call runs `list → preview → fetch`.
  - Assert that `/moodle/catalog.json` and `/materials/manifest.json` are written.
  - Assert that only the chosen files land under `courses/<id>/materials/…` and that `materials` rows are inserted.
  - Assert that a second run skips files that haven't changed.
  - With approval on, assert that an interrupt is raised and that the reject and edit paths work.
- **Live check:**
  1. Set `MOODLE_TOKEN` and `OPENROUTER_API_KEY`.
  2. `make db-init`, then create a course.
  3. Run `make note-taker COURSE=<uuid> MOODLE=<id> APPROVE=1`.
  4. Review the selection, approve it, then check the S3 objects and the `materials` rows.
- `make lint`, `make test`.
