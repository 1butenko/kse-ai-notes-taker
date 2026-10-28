# Lecture notes: implementation plan

Spec: `docs/superpowers/specs/2026-10-27-lecture-notes.md`. Branch `feature/lecture-notes`. Done before this plan: the spec (1626d77) and Start over safety (4818037).

## Approach

A lecture run is an ordinary notes run whose plan and transcript are cut down to one session before admission. `build_inputs`, the planner, writer, verifier, harmonizer, renderer, revisions, approval and the note page then work unchanged on that scope; the run records which session it belongs to. Positional session indices inside the run (`S0`) refer to the scoped transcript, so the UI maps runs to lectures by `run.session_id`, never by `topic_sessions`.

## Tasks

Each backend task is test-first with temporary data and the mock model, ends with `uv run pytest -q`, `ruff check` and `ruff format --check` green, and is one commit.

### 1. Scoped lecture runs (api, worker)

- `NotesRun.session_id: str | None` and `session_label: str | None` (None for legacy whole-course runs).
- `scope_to_session(plan, transcript, session_id) -> (Plan, Transcript)` in `app/plan.py`: keeps that session's entry and transcript session only, keeps course materials and language. 404 for an unknown session.
- `NotesRequest.session_id: str | None`. With it, the worker admits the scoped plan and transcript and records the session on the run; `materials` is the scoped fingerprint (so "readings changed" is per lecture for free).
- Planner: when the transcript has one session, the prompt asks for 1 to 4 topics that together cover that lecture, as one section.
- `POST /plans/{course}/sessions/{session_id}/notes` starts a run for one lecture (409 if the course has an active run). Existing `POST /plans/{course}/notes` stays for legacy resume only.
- Tests: inputs contain only the session's sources; planner prompt carries the 1 to 4 rule; run records session id and scoped fingerprint; unknown session 404.

### 2. Lecture-only files (api)

- Upload category `lecture` with a required `session_id`: stored under `<course>/lecture/<session_id>/`, attached to that session, marked `lecture_only` in the plan view's `FileView`.
- Not listed by `GET /uploads/{course}` readings, not offered to `/map` (which reads only `reading/`), not in `AddMaterialDialog`'s existing-file picker.
- Detach removes the attachment and the file (it belongs to nobody else).
- Tests: upload attaches and flags; other sessions and matching never see it; detach deletes it.

### 3. Course notation sheet (api, worker)

- `<course>/notation.json`: `{notation: [...], terminology: [...]}`, read with a tolerant loader (missing or unreadable means empty).
- Lecture runs pass it to the planner as binding notation; the plan's own entries are then merged append-only into the sheet when the run finishes (new symbols and terms only, existing meanings never rewritten).
- `GET /course-info/{course}/notation` for the view-only dialog.
- Tests: first run seeds it; second run receives it in the planner input and appends only new entries; a conflicting meaning does not overwrite.

### 4. Queue and stop (worker, api)

- Worker: per-course queue of session ids persisted in `<course>/queue.json` and the running `asyncio.Task` kept in memory. Each item, when it starts, loads the current plan and transcript from disk (the same helper the API uses), scopes it and runs it. One job per course (`ACTIVE`).
- Stop: cancels the task; `run_notes` catches cancellation, marks the run failed with "Stopped; resume to continue" (resumable: finished topics are reused) and the queue file is emptied. A worker restart fails the active run as today and drops the queue with a run warning.
- API: `POST /plans/{course}/notes/queue` (Generate all: every session without a lecture run that has readings, in syllabus order; returns the queue), `GET /plans/{course}/notes/queue`, `POST /plans/{course}/notes/stop`. Single-lecture generate (task 1) goes through the same queue so the two never race.
- Start over's 409 (already in place) also covers a non-empty queue.
- Tests: generate-all order and skip of sessions without readings; one job at a time; next item starts when one finishes or fails; stop cancels, marks resumable and clears; resume reuses finished topics.

### 5. Readings approval (api)

- `course.json` gains `readings_approved_at: str | None`. `POST /course-info/{course}/readings-approval` sets it, `DELETE` clears it.
- Re-reading or replacing the primary syllabus clears it (transcribe with force, transcript PUT that changes sessions, primary change).
- Tests: set, clear, cleared by re-read.

### 6. Web

- API client for tasks 1 to 5.
- Setup: after lecture approval and auto-matching, the **Readings per lecture** screen renders the existing `CoursePlan` unchanged with a summary of lectures needing attention and one *Approve readings* button. Course menu: *Readings per lecture*, *Course notation*.
- Course page (notes section): lecture rows with status from lecture runs and the queue; row click opens the latest finished lecture run's note, or the lecture page. Header: *Generate all*, *Stop* while the queue or a run is active. The whole-course *Generate notes* button goes; *Previous generations* lists legacy runs.
- Lecture page `/lectures/[session]`: empty state with *Generate note*; while generating, progress and *Stop*; its readings (excerpts and attached files, the existing session components) and a drop zone for lecture-only files; *Regenerate* with confirmation; *Readings changed* notice; *Previous versions* (older lecture runs, links to their notes); *Retry failed section* (resume).
- Note page: a **Lecture readings** link when `run.session_id` is set. Nothing else on that page changes (e2e tests pin it).

### 7. Verification and docs

- Web typecheck, lint, production build; browser checks on a mock-model stack of: readings review and approval, lecture empty state, generate, stop and resume, regenerate keeping the old version, generate all skipping a lecture without readings, lecture-only file absent from another lecture.
- The Quarto e2e suite needs Quarto installed; run it where available.
- README section on lecture notes.

## Order and risk

Tasks 1, 2, 3 and 5 are independent once 1 lands (they all touch `app/plan.py` or `routers/plans.py`, so they run one after another, not in parallel). Task 4 depends on 1. Task 6 depends on all. Highest risk: cooperative cancellation inside `run_notes` (rendering runs Quarto subprocesses; cancellation must not leave a half-written artifact manifest), and the scoped planner producing good sections for very short lectures.
