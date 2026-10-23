# Notes E2E suite

A browser suite for Quarto notes, run against a separate local stack:

| Process | Address | Notes |
| --- | --- | --- |
| Mock OpenRouter | `127.0.0.1:8126` | `api/tests/e2e/mock_openrouter.py`, LLM answers only |
| Worker | `127.0.0.1:8125` | real `app.worker.main`, real Quarto |
| API | `127.0.0.1:8124` | real `app.main` |
| Web | `127.0.0.1:3124` | `next dev --webpack` |

`stack.mjs` creates a fresh `kse-notes-e2e-*` root (under `/private/tmp` on macOS), seeds
course `local` from `api/tests/fixtures/notes`, starts the processes in order, checks each
one is ready, runs Playwright, and then stops the process groups it started, in reverse
order. The servers get an allowlisted environment with explicit overrides, so no `.env`,
production uploads, Moodle or OpenRouter keys reach them. If a port is already in use, the
run stops instead of reusing whatever is listening.

## Setup

```bash
cd api && uv sync
cd web && npm ci
npx playwright install chromium   # or: export NOTES_E2E_CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
```

Quarto is required. A missing Quarto stops the run with an error; it never counts as a pass.
Set `NOTES_E2E_QUARTO_BIN` (default `$QUARTO_BIN`, then `quarto`) and, for native Typst
fonts, `TYPST_FONT_PATHS`. The HTML preview loads MathJax from jsDelivr, so the browser
needs network access to `cdn.jsdelivr.net`.

## Run

```bash
cd web
npm run test:e2e:notes                       # full suite
npm run test:e2e:notes -- -g "preview"       # Playwright args after --
npm run test:e2e:notes -- --hold             # start the stack for manual QA; Ctrl+C stops it
NOTES_E2E_KEEP=1 npm run test:e2e:notes      # keep the root after a passing run too
```

When a run fails, the root is kept and its path is printed. It holds:

- `logs/{mock,worker,api,web}.log` and `logs/openrouter.jsonl` (schema, model, topic of each LLM call)
- `uploads/local/notes/<run>/` with `run.json`, `artifacts.json`, Quarto sources and `quarto-*.log`
- `playwright/report` (open with `npx playwright show-report <root>/playwright/report`)
- `playwright/results` with traces and failure screenshots (videos with `NOTES_E2E_VIDEO=1`,
  which also needs `npx playwright install ffmpeg`)

Failed tests also attach the logs and run files to the report. The preview test saves
desktop and 390 px screenshots as attachments on every run.

Override ports with `NOTES_E2E_{MOCK,WORKER,API,WEB}_PORT`, the Python interpreter with
`NOTES_E2E_PYTHON`, and the temporary directory with `NOTES_E2E_TMPDIR`.

## Synthetic data

`api/tests/fixtures/notes` is the only content source:

- `control.json`: a `NotesDocument` (schema 2, `uk`) with two topics, Ukrainian and English
  text, a definition, theorem, proof and example, matrices, indices, a long labelled formula,
  a captioned table, the registered figure `figure.png`, `@eq-`/`@tbl-`/`@fig-` and
  `Topic T1` cross-references, citations that produce a bibliography, and an unresolved
  T2 with one open major issue.
- `course-plan.json`: the plan the mock returns. The mock writes topic drafts from the
  control blocks without the figure, because a generated run has no registered assets yet.
- `reading/*.md`: the two session readings. Their chunk IDs and texts match the control
  evidence (`test_control_evidence_matches_seeded_readings`).
- `legacy-notes.json`: a pre-schema run without `schema_version`, `language`, `assets` or
  `verification_stale`. It is seeded as run `20261001-000000-0001`.

The mock picks its answer by response schema and by the `Topic T1:`/`Topic T2:` prompt
text. T1 passes verification. T2 keeps a major issue through every revision round, so it
ends unresolved for real. Unknown schemas get HTTP 500 and an `error` line in the log.

Backend checks for the same fixtures are in `api/tests/test_notes_fixtures.py`. The
real-Quarto render of the control document is opt-in:

```bash
cd api && QUARTO_TEST_BIN=/path/to/quarto TYPST_FONT_PATHS=... \
  NOTES_FIXTURE_OUTPUT=/tmp/control-render uv run pytest tests/test_notes_fixtures.py
```

The native fixture checks real figures and resolved references in HTML, PDF and DOCX.
HTML assertions use visible text: bundled AnchorJS contains `?@` in a script regex,
which is unrelated to unresolved references.

## Coverage today (`generation-smoke.spec.ts`)

1. `POST /plans/local/notes` returns 202. The test polls `GET /plans/local/notes/{run}` until
   the worker finishes, and fails at once if the run fails.
2. The document is schema 2, language `uk`; T1 is verified and T2 is unresolved with open issues.
3. Every required manifest entry (full notes, T1 and T2; HTML and PDF) is `ready` at revision
   0. A `done` run alone is not accepted.
4. The mock log shows all six generation schemas (`topic_suggestion` is only asked by the workflow suite), each with its `e2e/*` stage model, and
   repeated T2 verification.
5. The served bytes are real: the HTML has the sandbox CSP, `lang="uk"`, MathJax, equation
   and table anchors and the bibliography; the PDFs start with `%PDF-`; the T2 HTML links
   `@eq-t1-sarrus` into the full notes.
6. `figure.png` uploads through `POST .../assets` to the same digest path as the control
   fixture, and downloads again.
7. The legacy run loads through the API (schema 1, language recovered from the transcript)
   and its preview opens.
8. The preview renders MathJax in the sandboxed frame on desktop and on T2 (with the
   Unresolved badge). At 390 px, neither the page nor the notes body scrolls horizontally.

## Editing workflow (`notes-workflow.spec.ts`)

This file generates its own run, so the smoke run keeps revision 0. Revision numbers are
relative to the run's HEAD when each test starts. Saves and restores automatically render
HTML/PDF without calling the mock LLM.

1. **Edit, 409 and draft recovery.** Tab A edits the T1 Sarrus formula, adds a `remark`
   block and moves it up, ticks a citation from T1's evidence list, and saves. The API then
   has the next revision (`manual`, `changed_topics == ["T1"]`), a `b-<hex>` ID for the new
   block, T1 `unresolved` with `verification_stale`, T2 unchanged, and no new mock LLM
   calls. Going to T2 and back with browser Back still shows the new text revision and the
   correctly labelled artifact revision. Tab B started a draft on the old base: a focus refresh shows the newer revision
   and keeps the draft; Save gets the 409. After a reload the draft is found under its old
   base (sessionStorage key `…/T1@<base>`), shows what changed since that base, and saves
   only after an explicit transfer.
2. **History and restore.** An API edit of T2 is listed in History with a block diff (old
   and new text, added citation). Restoring the earlier revision creates a `restore`
   revision with `restored_from`; a new tab shows the same text revision and history.
3. **Leaving with a draft.** Topic links and the home link ask first ("Stay" keeps the
   text), closing the tab raises `beforeunload`, and after leaving the draft is offered
   again on return.
4. **Figure into the draft.** "Insert image" shows the upload validation error for a
   non-image, then puts the uploaded `figure.png` Markdown (`{#fig-t1-1}`) into the draft
   only; HEAD is unchanged until Save, after which `document.assets` lists the image.
5. **Unknown language.** A run written by the test with `language: null` needs an
   explicit uk/en choice before Save; saving unchanged blocks makes a metadata revision.
6. **Delayed responses.** A held response with the same text revision and older artifacts
   cannot overwrite a newer completed render in the browser.
7. **Saved and restored artifacts.** The image dialog inserts a figure into an empty block;
   after Save, the canonical revision HTML contains a real figure and resolved reference,
   and the actual PDF contains its caption and figure number. Restore renders its own
   revision. Disabling the stack's Quarto launcher (`<root>/quarto-disabled`) keeps the
   saved text, the new history entry and the previous HTML/PDF, each labelled with its own
   older revision; the Retry render button publishes current files when Quarto is
   re-enabled. These operations add zero model calls.

8. **AI suggestions and recheck.** The suggestion panel of the T1 editor: pick block 6,
   request "Explain this more simply", review the diff and the fresh check ("Verified against
   the sources"), and Reject. HEAD, the history and T1 are unchanged, and the worker's record is
   `rejected`. Requesting again and applying gives one `ai` revision with `suggestion` set; only
   block 6 of T1 differs, T2 is equal, T1 is `verified` (the check was of exactly that text),
   and the new revision gets real HTML/PDF with the suggested text. "Expand the example"
   inserts a `b-<hex>` block right after block 5. A suggestion on screen while T2 is saved over
   the API shows "The notes changed after this suggestion", has Apply disabled, and an API
   apply is a 409 that creates nothing. "Verify this topic again" on T2 records a
   `verification` revision with the same blocks; the mock still finds a major issue, so T2 stays
   Unresolved with that issue shown. Unit tests cover the 503 without OpenRouter.

9. **Word on demand.** A figure is added to T2 through the asset route and a save. On the
   full-notes preview, "Prepare Word" asks for DOCX of the current revision only
   (`POST .../revisions/{revision}/render {formats: ["docx"]}`); "Download Word" then saves
   `notes.docx` with `rev. N`. The test opens the file: the figure is in `word/media`, the
   caption, the heading text, a linked contents list (`Зміст`, `w:anchor="sec-T2"`, no `TOC`
   field) and native `<m:oMath>` equations are present. The API serves it with the Word media
   type, `attachment` and `X-Notes-Revision`. A later revision shows no current Word file, the
   old one is labelled "Older Word file · revision N", and its URL for the new revision is a
   404. With Quarto disabled, "Prepare Word" ends in an alert that says HTML and PDF are kept,
   HTML stays available, and "Retry Word" publishes the file after Quarto is back. Zero model calls.

## Planned scenarios (`notes-workflow.spec.ts`, currently `fixme`)

These follow the Task 12 plan. Each one is skipped until its interfaces land; check the
landed contracts again before writing the bodies.

1. **Course book.** Depends on Task 11 (book job and `.../revisions/{revision}/book/...`).
   Render the book → open it → search for a term from T2 → the result opens the right chapter
   of the same revision. Private textbooks and intermediate AI files do not appear in the
   search.

Visual QA stays manual, per the Task 12 brief: HTML at 390 px and on desktop, every page of
the control PDF, DOCX through the office QA compose (contents list, equation numbers, callout titles), and the book with search.

## Maintaining

- **Fixtures.** There is no generator script, so edit the JSON directly. `api/tests/test_notes_fixtures.py`
  checks it: a valid `NotesDocument` with no reference issues, the asset entry equal to
  `import_asset(figure.png)`, and sources/evidence equal to `build_inputs` over the seeded readings.
  Editing a reading changes its chunk ID (`<sha256[:8]>-0`), so update the `control.json`
  sources, evidence and citations to match. Replacing `figure.png` changes the asset digest
  and path.
- **New LLM steps.** When the worker gains a response schema (suggestions: `topic_suggestion`; re-verification reuses `topic_verification`), add it to `answer()` and `SCHEMAS` in `api/tests/e2e/synthetic.py`. The smoke
  asserts the exact set of schemas it sees, so update both together. An unknown schema
  fails the run on purpose.
- **Pipeline changes.** If topic structure or verification rules change, expected statuses
  (T1 verified, T2 unresolved) or call counts may shift. Adjust the fixture or mock when the
  product behaviour is intended, not the assertions on real artifacts.
- **Lockfile.** npm 11 `npm install` strips every `"libc"` field from `package-lock.json`,
  which changes how Linux/musl optional native packages resolve. When adding or upgrading
  test dependencies, keep the lockfile diff limited to the packages you change.
- **Figure/reference checks.** Keep real HTML figure/link assertions and PDF/DOCX text
  assertions. Do not scan raw HTML for `?@`: bundled scripts can contain that sequence.
- **Turning `fixme` into tests.** Check the landed routes and models first, then replace
  the body and drop `fixme`. Keep checks on actual artifacts and model-call counts.
