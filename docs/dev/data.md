# Data

The AI Note Taker's data is in Aurora PostgreSQL (IAM authentication, no password) and S3. The app's own course files (uploads, plans, syllabus) are on disk in the uploads directory. [schema.sql](../../api/app/schema.sql) is applied by `make db-init` (`uv run python -m app.manage init-db`) and is safe to run again.

## Tables

| Table | What it holds |
|---|---|
| `courses` | A course: `title`, `s3_prefix` (generated from `id`), `moodle_course_id`, `course_key` (the uploads folder name), `owner_id` |
| `materials` | Files fetched from Moodle: section, `s3_key`, `source_url`, `moodle_timemodified`. Unique per course, URL and modified time |
| `course_topics` | A course's Moodle sections: name and summary |
| `sync_runs` | One row per Moodle Note Taker run: `focus`, `status`, `step`, `todos`, `actions`, `report`, `error` |
| `lecture_note_runs` | One row per version of a lecture's notes (below) |
| `users` | Teachers: `google_sub`, `email`, names, `avatar_url`, `last_login_at` |

### `lecture_note_runs`

- `status`: `running`, `succeeded`, `failed` or `cancelled`. `step`, `todos`, `actions`, `report` and `error` show progress.
- `actions` (here and in `sync_runs`) is a JSON list of `{text, status, detail, todo}`, at most the latest 100 (`MAX_ACTIONS` in `note_taker/progress.py`). `todo` is the todo in progress when the action started; it is missing on older runs.
- `s3_prefix` and `files`: where the published page is and which files it has.
- `readings_fingerprint`: the lecture's readings when the run started (`app.plan.session_fingerprint`).
- `model`, `prompt_versions`, `langfuse_trace_id`, `renders`.
- `kind`: `agent` (written by the model, the default) or `edit` (a teacher's save, rendered without the model).
- `edited_from`: the run an `edit` started from (`ON DELETE SET NULL`). `edited_by`: the `users` row who saved it.
- `motivation` (jsonb, nullable): the motivation scout's decision on the note's opening hook: `needed`, `kind`, `device`, `reason`, `candidates`, `sources`. It is null for edits and for older runs. Run `make db-init` to add the column.
- A lecture's current notes are its newest `succeeded` run, found by `course_id`, `session_id` and `started_at`. Older runs stay as earlier versions.

## S3 keys

| Key | Holds |
|---|---|
| `courses/<course-id>/course.json` | Manifest: id, title, created_at |
| `courses/<course-id>/materials/<file-id>/<file-name>` | Files fetched from Moodle |
| `courses/<course-id>/lecture-notes/<session>/<run>/` | A published version: `index.html`, `index_files/`, `assets/*.svg`, `fonts/`, `lecture-notes.css`, `index.qmd` |

Key builders are in [storage.py](../../api/app/storage.py). An edit writes a new `<run>` prefix; a re-render (`rerender.py`) replaces the files under the run's existing prefix.

## Files on disk

`UPLOADS_DIR` (default `uploads/`) holds each course's folder, named by the course key. The API creates it at start. Course layout inside it is set by `routers/uploads.py` and `plan.py`; not described further here yet.

## Browser storage

The notes editor keeps an unsaved edit in `localStorage` under `kse-notes:draft:<run-id>` (`web/src/components/lecture-notes/editor/draft.ts`).
