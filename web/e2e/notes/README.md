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

It currently records one known defect as a strict `xfail`: a block whose content starts
with a figure loses the figure, and `@fig-…` renders as `?@fig-…` in HTML, PDF and DOCX.

## Coverage today (`generation-smoke.spec.ts`)

1. `POST /plans/local/notes` returns 202. The test polls `GET /plans/local/notes/{run}` until
   the worker finishes, and fails at once if the run fails.
2. The document is schema 2, language `uk`; T1 is verified and T2 is unresolved with open issues.
3. Every required manifest entry (full notes, T1 and T2; HTML and PDF) is `ready` at revision
   0. A `done` run alone is not accepted.
4. The mock log shows all six pipeline schemas, each with its `e2e/*` stage model, and
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

## Planned scenarios (`notes-workflow.spec.ts`, currently `fixme`)

These follow the Task 12 plan. Each one is skipped until its interfaces land; check the
landed contracts again before writing the bodies.

1. **Edit and history.** Depends on Task 6 (revisions API), Task 7 (editor, diff, restore
   UI) and Task 8 (revision render jobs and artifact routes).
   Open HTML preview → edit a T1 block → save with `base_revision` → the text revision becomes 1
   → poll the render job until revision 1 HTML/PDF are `ready` → the preview shows "Text
   revision 1" with no "Older artifact" note → history lists 0 and 1 → restore 0 → this
   creates revision 2 with the old text, `verification_stale` and a fresh render. A second
   save with the old base gets HTTP 409. A forced render failure (for example, an invalid
   label in a saved block) keeps the content and the previous ready artifact.
2. **AI suggestion review.** Depends on Task 9 (suggestions API and UI). The mock needs
   answers for the suggestion and re-verification schemas once they are named.
   Request a suggestion for one block → reject it, and the revision is unchanged → request
   again → apply with `base_revision` → a new revision is created and only that topic changes.
3. **Word and book.** Depends on Task 10 (DOCX revision artifacts) and Task 11 (book job
   and `.../revisions/{revision}/book/...`).
   Download the DOCX for the current revision (check the media type, that the figure is in
   `word/media`, and the text) → render the book → open it → search for a term from T2 →
   the result opens the right chapter of the same revision. Private textbooks and
   intermediate AI files do not appear in the search.

Visual QA stays manual, per the Task 12 brief: HTML at 390 px and on desktop, every page of
the control PDF, DOCX through the office QA compose, and the book with search.
