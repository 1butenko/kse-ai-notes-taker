# API (FastAPI)

The API (`api/app/`) serves the web app. It checks who is calling, keeps course files in the uploads directory, and keeps the AI Note Taker's data in Aurora PostgreSQL and S3. Model calls are not made here: the API asks the [worker](worker.md) over HTTP (`worker_client.py`). It runs as the `api` service in Docker Compose (port 8000).

## Layout

| File or folder | What it holds |
|---|---|
| [main.py](../../api/app/main.py) | App setup: CORS, router wiring, `/health` |
| [config.py](../../api/app/config.py) | `Settings` (env vars: Moodle, S3, DB, worker URL, auth secret, `SHARED_COURSES`) |
| [auth.py](../../api/app/auth.py) | Token check and course/run ownership dependencies |
| [db.py](../../api/app/db.py), [schema.sql](../../api/app/schema.sql) | Aurora connection (IAM auth) and the schema |
| [storage.py](../../api/app/storage.py) | S3 key layout and helpers |
| [moodle.py](../../api/app/moodle.py) | Moodle web-service client |
| [plan.py](../../api/app/plan.py), [course.py](../../api/app/course.py), [syllabus.py](../../api/app/syllabus.py), [books.py](../../api/app/books.py), [links.py](../../api/app/links.py) | Course plan, course info, syllabus, books and web links |
| [worker_client.py](../../api/app/worker_client.py), [worker_contract.py](../../api/app/worker_contract.py) | Calls to the worker and their request/response models |
| [routers/](../../api/app/routers/) | One module per route group (below) |
| [note_taker/](../../api/app/note_taker/) | The AI Note Taker; see [docs/note-taker/](../note-taker/overview.md) |
| [manage.py](../../api/app/manage.py) | `init-db`, `list`, `claim-course` |

## How it works

- **Auth.** The web's `/api/*` route handler forwards each call with a 60-second HS256 token signed with `API_AUTH_SECRET`. `sub` is `users.id`, or `worker`/`web` for services. `main.py` puts `current_principal` on every router; `plans` and `agent` also check `owned_course`. A teacher owns the courses with their `courses.owner_id`; courses in `SHARED_COURSES` are open to every teacher.
- **Public routes.** Only `lecture_notes.site_router` (the published page files) is open without sign-in. The run id in the URL is unguessable, and the HTML is served in a sandbox.
- **Long jobs.** Routes that start a model job insert a row (`sync_runs`, `lecture_note_runs`), call the worker, and return 202. The web polls the row.
- **Lecture notes.** See [lecture-notes.md](../note-taker/lecture-notes.md) for runs. Editing: `POST /lecture-notes/runs/{run}/edits` checks that the version is published and the lecture's readings are unchanged (409 otherwise), validates the body with `validate_body` (422 with `[{line, message}]`), inserts an `edit` run (`runs.start_edit`) and asks the worker to render it (`WorkerClient.edit_lecture_notes`). A worker failure marks the run failed.
- **Current version.** `current_run(run_id)` returns the newest succeeded run of the same lecture. `site/{path}` serves that run's files whichever run the link names.

## Interfaces

| Prefix | Router | Purpose |
|---|---|---|
| (none) `/auth/sync`, `/me` | [auth.py](../../api/app/routers/auth.py) | Record a signed-in teacher; read and update their profile |
| `/courses` | [courses.py](../../api/app/routers/courses.py) | Connect a Moodle course, read it and its contents |
| `/course-info` | [course_info.py](../../api/app/routers/course_info.py) | Course info, readings approval |
| `/uploads` | [uploads.py](../../api/app/routers/uploads.py) | Upload files, add Moodle files and links |
| `/syllabus` | [syllabus.py](../../api/app/routers/syllabus.py) | Syllabus transcription and transcript |
| `/plans` | [plans.py](../../api/app/routers/plans.py) | Course plan: sessions, files, mapping, proposals |
| `/files` | [files.py](../../api/app/routers/files.py) | Read an uploaded file |
| `/agent/courses` | [agent.py](../../api/app/routers/agent.py) | The Moodle Note Taker agent: course state, `POST /{course}/sync` |
| `/lecture-notes` | [lecture_notes.py](../../api/app/routers/lecture_notes.py) | Lecture-notes runs, edits and the published page |

Lecture-notes routes:

| Route | Purpose |
|---|---|
| `POST /lecture-notes/{course}/{session}/runs` | Start an agent run |
| `GET /lecture-notes/{course}/{session}/runs` | The lecture's runs, newest first |
| `GET /lecture-notes/runs/{run}` | One run, to poll |
| `POST /lecture-notes/runs/{run}/cancel` | Cancel |
| `GET /lecture-notes/runs/{run}/source` | The editor's input: `{run_id, body, assets[], references[{id, title}]}`. 409 unless the run is published |
| `POST /lecture-notes/runs/{run}/edits` | Body `{body, assets: {name: svg}}`. 202 with the new `edit` run; 409 (not published, or readings changed); 422 with the problems |
| `GET /lecture-notes/runs/{run}/site/{path}` | Public. The lecture's newest published file; `index_files/` is immutable, the rest `no-cache` |

A run in the API (`LectureNotesRun`) has `kind` (`agent` or `edit`), `edited_from` and `edited_by`.

## Conventions and gotchas

- Errors from S3 or the database go through `storage_errors()` (in `routers/agent.py`) so they become 503s, not 500s.
- Blocking code (DB, S3) in `async` routes runs through `asyncio.to_thread`.
- New course routes need an ownership check: `owned_course`, `owned_path` or `owned_run`.
- Changing a worker request means changing `worker_contract.py`, `worker_client.py` and `worker/main.py` together.
- The schema is `CREATE ... IF NOT EXISTS` plus `ALTER ... ADD COLUMN IF NOT EXISTS`; run `make db-init` after changing it.
