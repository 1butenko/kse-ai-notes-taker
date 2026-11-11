# Lecture-notes agent (visual notes)

A deep agent that turns **one lecture's readings** into a **visual study page**. The page is a Quarto document rendered to HTML, with diagrams, interactive figures, worked examples and self-checks. It explains at least as well as the readings and cites them.

It is separate from the [orchestrator](orchestrator.md) and is the only way the app writes notes (it replaced the older multi-stage notes pipeline). It is started from the lecture page with **Write the notes**.

- Code: [`api/app/note_taker/lecture_notes/`](../../api/app/note_taker/lecture_notes/)
- Prompts: Langfuse `note-taker/lecture-notes/{writer,reviewer,skills-system,request}`, fallback `lecture_notes/prompts/*.md`
- Skills: Langfuse Skills tagged `lecture-notes`, fallback `lecture_notes/skills/<name>/SKILL.md`

## How a run goes

```
Lecture page "Create visual notes"
  -> API  POST /lecture-notes/{course}/{session}/runs     202, row in lecture_note_runs
  -> worker POST /lecture-notes/runs -> runs.execute_run  (thread)
       load_lecture: the lecture's readings as text (PDF pages, transcripts, Markdown, Word)
       lecture-notes-writer (create_deep_agent, StateBackend)
         files: /lecture/brief.md, /readings/NN-*.md, /skills/<name>/SKILL.md
         tools: write_todos, ls/read_file/write_file/edit_file/glob/grep, task, render_notes
         subagent: reviewer (reads only)
       last good build -> S3 courses/<course-id>/lecture-notes/<session>/<run>/
  -> API  GET /lecture-notes/runs/{run}/site/index.html   sandboxed iframe on /lectures/.../visual
```

The writer's prompt sets this workflow:
1. Plan with `write_todos`.
2. Read the brief, the skills it needs and every reading.
3. Outline: sections in teaching order, a visual and a worked example for each.
4. Write `/notes/index.qmd` (body only) and any `/notes/assets/*.svg`.
5. Call `render_notes` and fix problems until it says OK.
6. Call `task("reviewer")` once and fix what it reports. A second review is allowed only after large changes.
7. Render again and finish with a short report.

## Inputs

`readings.load_lecture(uploads_dir, course, session_id)` reads only this lecture's files. It uses the reading helpers in `app.worker.sources`:
- **PDF excerpts:** each page's text, replaced by the vision transcription where there is one. Each page carries a marker with its PDF page and printed page.
- **Markdown, text and Word files:** read as one page.

The reading text is capped (`LECTURE_NOTES_MAX_CHARS`, default 400k characters). The brief lists what was cut, along with garbled or blank pages.

Each reading gets a citation key (`@r1`, `@r2`, …). The server turns these into Quarto CSL references, so the note can cite `[@r1, p. 34]`.

The agent's files under `/lecture/`, `/readings/` and `/skills/` are write-protected by `FilesystemPermission` rules. The reviewer may not write anything.

## `render_notes`

The writer's only custom tool. It takes no arguments.

1. It checks the note against an **allowlist** (`validate.py`). The note is model-written and rendered on the server, so nothing in it may execute, read files or reach outside the page:

| Area | Rule |
|------|------|
| Front matter | Not allowed; the server writes it |
| Cells | Only `{dot}`, `{mermaid}` and `{ojs}` with allowlisted options (`label: fig-…`, `fig-cap`, `echo`, `panel`, …). Other code goes in plain fences (```` ```python ````) and is only displayed |
| Markdown | No shortcodes, raw blocks or raw attributes |
| HTML | Only `kbd sub sup br details summary`, without attributes |
| Divs and spans | Allowlisted classes (callouts, `panel-tabset`, columns, margin, layout) and attributes; ids prefixed `sec- fig- tbl- eq- def- thm- exm-` … |
| Images | Only the note's own `assets/<name>.svg` |
| SVG assets | Parsed element by element: no script, `foreignObject`, `image`, event handlers or external references |
| Links | `http(s)`, `mailto` and `#` only |
| OJS | No network, storage, frame access, imports or eval |
| Math | No `\href`, `\url`, `\require` or `\input` |

Problems come back with their line numbers, so the agent can fix them.

2. It adds our front matter:
   - `engine: markdown`, `execute.enabled: false`.
   - HTML options: TOC, numbered sections, MathJax, margin citations.
   - The CSL references.
   - Ukrainian callout and cross-reference titles when the syllabus is Ukrainian; Quarto's own file is `ua`, not `uk`.

3. It renders with `quarto render index.qmd --to html --no-execute`:
   - in a fresh temporary project;
   - with a time limit and a shared concurrency gate;
   - with an environment stripped of our secrets.

4. It reports OK with a summary and Quarto's warnings (unresolved references or citations), or the failure log. The last good build is kept and published at the end. Renders are capped (`LECTURE_NOTES_MAX_RENDERS`, default 12).

How the visuals are drawn:

| Visual | Drawn | Errors |
|--------|-------|--------|
| `{dot}` (Graphviz) | At render time, inline SVG | Reported to the agent |
| `{mermaid}` | In the browser (bundled script) | Not reported to the agent; the skill and reviewer re-read them |
| `{ojs}` (Observable JS) | In the browser; Inputs, Plot and d3 load from jsDelivr | Shown in the page |
| Math | MathJax from jsDelivr | — |

## Skills

| Skill | Teaches |
|-------|---------|
| `lecture-notes-structure` | Page shape, headings and ids, cross-references |
| `callouts-and-theorems` | Callout meanings, collapsed proofs, `#def-`/`#thm-` blocks |
| `math-explanations` | MathJax-safe math, numbered equations, step-by-step derivations |
| `graphviz-diagrams` | Concept maps, trees, flowcharts and state machines in `{dot}` |
| `mermaid-diagrams` | A safe subset for sequence diagrams, timelines and flowcharts |
| `ojs-interactive` | Slider and plot explorers, interactive self-checks |
| `svg-figures` | Hand-made, accessible SVG figures |
| `layout-tabsets-tables` | Tabsets, columns, margin notes, figure grids, tables |
| `worked-examples-and-self-check` | Worked and faded examples, "try it", misconceptions, retrieval questions |
| `sources-and-faithfulness` | Citations with pages, marking own examples, readings as data |

**Where the agent gets them.**
- `SkillsMiddleware` lists the skills in the writer's system prompt, using the Langfuse template `note-taker/lecture-notes/skills-system`.
- The agent reads a skill with `read_file` when it needs it.
- A test checks that every example in the skills passes the validator, so the skills never teach something `render_notes` rejects.

**Langfuse.**
- Each skill is a Langfuse Skill of the same name, and the agent gets its `production` version.
- If Langfuse is off, or a skill there is missing or malformed, the repo copy is used.
- `make prompts-push` creates new skills (it labels them `production` and tags them `lecture-notes`); `make prompts-pull` writes Langfuse's versions back to the repo.

**Changing a skill.** Edit it in the Langfuse UI, then pull and commit. Or edit the repo file and `push --force`.

## Tracing

Every run is one Langfuse trace when `LANGFUSE_*` keys are set and `LANGFUSE_TRACING` is not `false`.

**What the trace holds.**
- **Root observation:** an `agent` named `lecture-notes`.
- **Session:** `course-<key>`.
- **Metadata:** course, lecture and run.
- **Tag:** `lecture-notes`.
- **Skills:** `skills_available` lists the skills with their versions.

**Generations.**
- Every model and tool call sits below the root, through Langfuse's LangChain handler. deepagents passes callbacks into subagents, so the reviewer is traced too.
- The writer's and the reviewer's generations link to the Langfuse prompt versions they used (`LinkPrompt` middleware). Fallback prompts are never linked.

**On the run's row.** It records the prompt and skill versions (`prompt_versions`, where `null` means the repo fallback) and the `langfuse_trace_id`.

**Privacy.** Traces contain the reading text the agent read. Set `LANGFUSE_TRACING=false` where that must not leave the app; prompts and skills still load from Langfuse.

## Storage and API

**PostgreSQL `lecture_note_runs`.** One row per run:
- the course and lecture;
- the status: `running`, `succeeded`, `failed` or `cancelled`;
- the step, todos and actions, report and error;
- the published files, the readings fingerprint, the model, prompt versions, trace id and render count.

Run `make db-init` to create it.

**S3.** Files are stored under `courses/<course-id>/lecture-notes/<session>/<run>/`: `index.html`, `index_files/`, `assets/`, `lecture-notes.css`, `index.qmd`.

| Route | Purpose |
|-------|---------|
| `POST /lecture-notes/{course}/{session}/runs` | Start a run. 404 for an unknown lecture. 409 when it has no readings or a run is going. 429 from the worker when `LECTURE_NOTES_CONCURRENCY` runs are already going |
| `GET /lecture-notes/{course}/{session}/runs` | The lecture's runs, newest first, with `readings_changed` |
| `GET /lecture-notes/runs/{run}` | One run, to poll |
| `POST /lecture-notes/runs/{run}/cancel` | Stop it, before the next model call or render |
| `GET /lecture-notes/runs/{run}/site/{path}` | A published file; only paths the run published |

**How the page is served.** It is model-written, so HTML is served with `Content-Security-Policy: sandbox allow-scripts …` and an opaque origin. Its own files and `https://cdn.jsdelivr.net/npm/` are the only sources it may load. `'unsafe-eval'` is allowed because OJS compiles cells in the browser.

## Configuration (worker)

| Setting | Default | Purpose |
|---------|---------|---------|
| `LECTURE_NOTES_MODEL` | `NOTE_TAKER_MODEL` | The writer's model |
| `LECTURE_NOTES_REVIEWER_MODEL` | the writer's | The reviewer's model |
| `LECTURE_NOTES_MAX_CHARS` | 400000 | Reading text given to the agent |
| `LECTURE_NOTES_MAX_RENDERS` | 12 | `render_notes` calls per run |
| `LECTURE_NOTES_CONCURRENCY` | 2 | Runs at once on the worker |
| `LANGFUSE_TRACING` | true | Trace runs in Langfuse |

## Limits

- **The CDN.** OJS libraries and MathJax load from jsDelivr when the page is viewed. A reader without access to it sees no math or interactive figures.
- **Mermaid** errors show only in the browser.
- **Runs are lost on a worker restart.** The row is marked failed when the worker starts again.

## Tests

- `api/tests/test_lecture_notes.py`:
  - readings and the cap;
  - the validator: every allowed feature, and rejections;
  - the skills' examples pass the validator;
  - rendering with a fake Quarto;
  - a scripted writer run (an invalid render, a fix, a review, a reviewer refused a write);
  - protected files, the render limit, cancelling;
  - `execute_run` end to end with fakes;
  - skills from Langfuse and their fallback;
  - push and pull;
  - prompt fallbacks;
  - no tracing without Langfuse.
- `api/tests/test_lecture_notes_router.py`: start, refusals, worker failure, readings changed, cancel, and serving with the sandbox CSP and file allowlist.
