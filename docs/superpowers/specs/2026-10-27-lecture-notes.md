# Lecture notes: one note per lecture, generated on request

Status: agreed with the lecturer 2026-10-27 (grilling session), not implemented. Branch `feature/lecture-notes`, from `feature/simple-ui`. The Quarto notes spec, the revision architecture and teacher approval remain binding for everything inside a run.

## User behavior

Setup keeps the simple-ui flow up to the lectures: create a course (name, one syllabus, readings, Moodle import), the syllabus is read automatically, the lecturer edits and approves the lectures. Readings are then matched automatically, and a new **Readings per lecture** screen lists each lecture with its matched excerpts (page ranges editable, *Check pages* and *not found* flags), its files and *Add material*. Lectures needing attention sort first. One **Approve readings** button leads to the notes section. The screen stays reachable from the course menu.

The **notes section** (the course page) lists every lecture with its status: *No note*, *Queued*, *Writing*, *Verified*, *Unresolved*, *Readings changed*. Clicking a lecture with a note opens its note (the existing note page, plus a **Lecture readings** link back). Clicking a lecture without one opens its **lecture page**: "This lecture has no note yet", *Generate note*, its readings, and a drop zone for **lecture-only files**.

No note is generated until the lecturer asks. *Generate note* writes one lecture. **Generate all** queues every lecture without a note that has readings (matched excerpts or lecture-only files) and skips the rest with "No readings". The queue runs on the server, one lecture at a time, and survives closing the tab. **Stop** cancels the lecture being written and clears the queue; the stopped lecture keeps its finished sections and offers *Resume*, which never rewrites them.

**Regenerate** on a lecture with a note asks first, keeps showing the current note until the new one is ready, then moves the old one to that lecture's **Previous versions** with its edits and approval. When a lecture's readings change after its note was written (a file dropped, an excerpt's pages changed, a file detached), its row and page say "Readings changed since this note was written". Nothing regenerates on its own.

A lecture whose sections partly fail shows its note with the failed sections marked and *Retry failed section* (which resumes the run).

The course menu adds **Readings per lecture** and **Course notation** (view-only). Existing whole-course runs stay readable under *Previous generations* and never appear in the lecture list.

## Contracts

- **Scope of a generation.** One run per lecture, keyed by the plan's session id. Its inputs are that session's attached files and approved excerpts plus its lecture-only files, frozen at admission as today (`inputs.json`, provenance). Retrieval never reaches other lectures' sources or whole books.
- **Planning inside a lecture.** The planner sees one session (its topic, subtopics, readings) and the course notation sheet, and returns 1 to 4 topics that become the sections of the lecture's note. Coverage review applies to that session only. Topic ids stay `T1..Tn` within the run.
- **Course notation sheet.** Stored per course. Empty until the first lecture run finishes; that run's notation and terminology seed it. Each later run receives it as binding context and its new entries are appended (never rewriting existing ones). Consistency harmonization runs within a lecture run only.
- **Lecture-only files.** Uploaded under the course but attached to one session and flagged lecture-only; they appear only on that lecture's page and in that lecture's inputs, never in the course readings panel or in matching. Detaching deletes nothing else.
- **Queue and stop.** Server-side per course: an ordered list of session ids plus the active run. One worker job per course at a time (today's `ACTIVE` rule). Stop cancels the active job cooperatively, marks its run interrupted (resumable, finished topics reused) and empties the queue. A worker restart fails the active run as today; the queue resumes with the next lecture only when the API next starts a job.
- **Readings changed.** A per-session materials fingerprint recorded on the run at admission, compared with the session's current one.
- **Approval state.** Lecture approval stays `plan.mapped`. Readings approval is stored in `course.json` (time of approval). Re-reading or replacing the syllabus clears it.
- **Lecture identity.** Runs attach to the session id. When a syllabus change removes a session, its runs stay readable under *Previous generations*.
- **Start over safety (first, separate commit).** `DELETE /course-info/{course}` returns 409 while any run of the course is queued or running or its queue is non-empty, and moves the course folder to a trash folder under the uploads root instead of deleting it. The UI disables *Start over* with the reason while generating.

## Out of scope

Editing the notation sheet; running several lectures in parallel; a combined course document or PDF across lectures; deduplicating content between lectures.

## Required validation

API and worker tests with temporary data and the mock model: per-lecture inputs contain only that lecture's sources; lecture-only files are absent from other lectures and from matching; planner 1 to 4 topics for one session; notation sheet seeding and append-only growth; queue order, skip of lectures without readings, one job at a time; stop cancels, clears the queue, and resume reuses finished topics; regenerate keeps the old run under previous versions; readings-changed detection per lecture; legacy whole-course runs listed but not in lectures; start-over 409 while active and trash move. Web: typecheck, lint, production build; browser checks of the lecture page empty state, generate, stop, resume and regenerate.
