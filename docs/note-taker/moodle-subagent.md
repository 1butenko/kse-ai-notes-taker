# `moodle` subagent

The first subagent of the [AI Note Taker](overview.md). Given one course, it lists everything in Moodle, decides what is relevant for note-taking, downloads that to S3 and writes a manifest. It cannot write notes.

- Spec: [`subagents/moodle.py`](../../api/app/note_taker/subagents/moodle.py)
- Prompt: Langfuse `note-taker/moodle`, fallback [`prompts/moodle.md`](../../api/app/note_taker/prompts/moodle.md)
- Code: [`api/app/note_taker/moodle/`](../../api/app/note_taker/moodle/)

## How it runs

The orchestrator calls `task("moodle", …)` with a complete instruction. The subagent then follows its prompt:

1. `list_course_contents` to see every section, activity and file.
2. Decide what is relevant, using `preview_module` when a name or type is not enough.
3. `fetch_materials` once with the whole selection, with a one-line reason per item.
4. Reply with a short summary. The details are in `/materials/manifest.json`.

Relevance is decided by the model from names, types, mimetypes, sizes, section titles and previews, guided by rules in the prompt:

| Keep | Skip |
|------|------|
| Slides, lecture PDFs, handouts, readings, textbook chapters, lab sheets | Forums, quizzes, attendance, feedback, choices, surveys, chats, assignments |
| `page` and `book` modules with real content, `folder` modules with documents | Videos and other media over about 100 MB, archives, duplicates |
| One copy of a document: the PDF when a PPTX exists too | Navigation, announcements, labels without teaching content |

`url`, `page` and `book` modules are saved as Markdown readings of their web pages (see `fetch_materials`). The outline shows where each `url` module points (`-> <target>`), so lecture slides published as web pages (Quarto, reveal.js) are easy to recognize. If the request names a focus topic, the subagent keeps only matching sections and says what it left out.

## Tools

All three are built by `make_moodle_tools` in `moodle/tools.py`. The course id and Moodle course id are bound into them by closure, so the model cannot choose another course.

### `list_course_contents()`
Calls Moodle's `core_course_get_contents`, normalizes it into a flat catalog, and saves the full JSON to `/moodle/catalog.json`. It returns one line per module, grouped by section:

```
## Section 1: Week 1 - Intro
- [10] resource: Slides | slides.pdf (application/pdf, 1 KB)
- [12] quiz: Quiz 1
```

Hidden sections and modules are dropped because the token cannot access them. Each call refreshes the catalog.

### `preview_module(module_id, max_chars=2000)`
Reads a module's text so the model can judge it without downloading:

| Module type | Returns |
|-------------|---------|
| `page`, `book` | The HTML content files as Markdown |
| `label` | The label's text |
| `url` | The link target and the start of its page as Markdown (or: a video, a PDF) |
| other (files) | File names, mimetypes and sizes |

An unknown `module_id` returns a hint to call `list_course_contents`.

### `fetch_materials(items)`
Each item is `{module_id, filename?, reason}`. Omit `filename` to fetch all files of the module.

- **Resolved against the catalog.** An id not in the catalog fails, so the model cannot invent URLs. A `filename` that does not exist in the module also fails.
- **Web pages become Markdown.** `url`, `page` and `book` modules go to the app's `POST /uploads/moodle/links`, which saves each as one `.md` reading: the linked page (a PDF link stays a PDF), or the module's HTML read from Moodle with the token (a book's chapters in order). `app/links.py` `html_to_markdown` keeps headings, lists, tables, code, LaTeX (`$…$`, `$$…$$`) and absolute links and images, including reveal.js `data-src` images. These readings are not stored in S3 or the `materials` table.
- **Excluded types are refused.** Modules of types such as `quiz`, `forum` or `assign` (`SKIP_MODNAMES` in `moodle/catalog.py`) are skipped even if requested, as a second line of defence behind the prompt.
- **Streamed, not buffered.** Each file streams from Moodle to S3 at `courses/<course-id>/materials/<file-id>/<name>` via `storage.upload_stream`. Moodle sometimes answers a bad token or missing permission with a JSON error and HTTP 200. The client detects this and raises instead of storing the error as a file.
- **Skips unchanged files.** A file is skipped when the `materials` table already has the same course, `source_url` and `timemodified`. A re-run downloads only what changed.
- **Records each file** in the `materials` table (S3 key, size, mimetype, source, reason).
- **One failure does not stop the rest.** Failed files are listed in the result and the manifest.

It writes `/materials/manifest.json` and returns counts plus failures:

```json
{
  "fetched": [{"module_id": 10, "name": "slides.pdf", "source_url": "…", "reason": "lecture slides", "s3_key": "courses/…/slides.pdf", "size": 8}],
  "skipped": [{"module_id": 12, "name": "Quiz 1", "reason": "…", "why": "quiz modules hold no study material"}],
  "failed":  [{"module_id": 99, "error": "not in the course catalog"}]
}
```

The manifest accumulates across calls within one run.

## Human approval

With `approval=True` the spec sets `interrupt_on={"fetch_materials": True}`. The run pauses before the download so a person can see the chosen items and reasons, and approve, edit (prune the list) or reject. This needs the orchestrator's checkpointer and a `thread_id`. The resume loop will ship with the CLI and is not tested yet.

## Moodle client

[`moodle/client.py`](../../api/app/note_taker/moodle/client.py) is a synchronous `httpx` client for the REST web services at `<MOODLE_URL>/webservice/rest/server.php`.

| Method | Use |
|--------|-----|
| `call(wsfunction, **params)` | Generic call. Raises `MoodleError` on a Moodle exception payload |
| `get_course_contents(moodle_course_id)` | Sections, modules and files |
| `iter_download(fileurl)` | Streams a file's bytes with the token. Raises `MoodleError` on a JSON error body |
| `get_page_html(fileurl)` | HTML of a `page` or `book` content file |

A missing `MOODLE_URL` or `MOODLE_TOKEN` raises `MoodleError("notconfigured", …)` on first use, not when the agent is built.

## Data

| Where | What |
|-------|------|
| `/moodle/catalog.json` | Full catalog (virtual filesystem, per run) |
| `/materials/manifest.json` | Fetched, skipped and failed items (virtual filesystem, per run) |
| S3 `courses/<course-id>/materials/<file-id>/<name>` | The files, see [storage.md](../storage.md) |
| PostgreSQL `materials` | One row per stored file. Unique on `(course_id, source_url, moodle_timemodified)` |

Run `make db-init` once to create the `materials` table.

## Limits

- **Pages rendered by JavaScript** have no text in their HTML and fail with "no text"; there is no headless browser.
- **Catalog and manifest** exist only for the run. The durable record is the `materials` table and S3.
- **Course scope only.** The tools cannot reach other courses, but the token can, so use a Moodle token with the least rights it needs.

## Tests

[`api/tests/test_moodle_subagent.py`](../../api/tests/test_moodle_subagent.py), with a fake Moodle client, an in-memory materials store and a stub uploader: catalog and outline, previews without downloads, fetch results and manifest, skipping unchanged files, failures, bad file names, the subagent spec and approval gate, and a full run from the orchestrator through `task("moodle")`.
