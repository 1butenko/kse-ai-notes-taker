# Agent architecture audit

Based on `main` at `4ae732c` ("Remove Langfuse tracing"), 2026-11-06.

## TL;DR

- **There is no autonomous agent.** No agent framework (deepagents, LangGraph) and no model-driven tool loop. Notes are made by a **fixed pipeline of structured-output LLM calls** that Python code drives step by step. The model never picks the next step.
- **Everything AI runs in one service: the `worker`.** The API (`api`) never calls a model; it forwards to the worker over HTTP (`WorkerClient`).
- **Every model call goes through OpenRouter** using strict JSON schemas. Model names come from config.
- **Nothing is stored in a database.** All state is JSON files under `UPLOADS_DIR` (a Docker volume). Retrieval is plain BM25 with no embeddings.
- **Generation is slow and runs in the background.** The worker returns `202`, and the run continues as a FastAPI background task.

## 1. Services

```
web (Next.js :3000) ──/api/*──► api (FastAPI :8000) ──HTTP──► worker (FastAPI, internal)
                                  │ Moodle, uploads, plan,        │ every LLM call (OpenRouter)
                                  │ run/revision reads            │ PDF reading, BM25, Quarto render
                                  └────────── shared volume `uploads` (/data/uploads) ──────────┘
```

| Service | Role |
|---|---|
| `api` | Moodle import, file uploads, course plan (syllabus sessions ↔ readings), read views of runs and revisions. Forwards every AI action to the worker. |
| `worker` | Owns OpenRouter. Image `typeset` = API image + Quarto (Typst PDF). Takes a file lock (`.worker.lock`) on `uploads_dir`, so **only one worker instance can run**. |
| `web` | Dashboard: Moodle import, syllabus, readings, lectures, notes editor. |
| Demo | `render.yaml` / `demo/start.sh` run API and worker in one container. |

## 2. What happens after a teacher submits textbooks

Stage order, with the model call each stage makes. "No model" stages are plain code.

| # | Stage | Trigger | What runs | Model call |
|---|---|---|---|---|
| 1 | **Upload** | `POST /uploads`, `/uploads/moodle`, `/uploads/moodle/links` | API saves the file to `uploads/<course>/{syllabus,reading}/`. Moodle links become `.md` (HTML to text) or `.pdf`. | none |
| 2 | **Syllabus transcription** | `POST /syllabus/transcribe` → worker `/transcribe` | PDF is sent as a file part (OpenRouter native PDF parser). DOCX is converted to HTML with mammoth. Output: `SyllabusExtraction` (materials list, sessions, readings, pages, language). | `extract-reading-plan` (`openrouter_model`, default `google/gemini-3.1-flash-lite`) |
| 3 | **Course plan sync** | after transcript is saved | `plan.sync` aligns plan sessions with transcript sessions. | none |
| 4 | **Map materials** | `POST /plans/{course}/map` → worker `/map` | Builds a `BookIndex` per PDF (outline/bookmarks via pypdf). Then 4a, 4b, 4c below. | see below |
| 4a | match citations to files | | Match each syllabus material and loose citation to an uploaded file. | `match-books` |
| 4b | read the table of contents | only if the PDF has no outline | Reads the TOC pages visually. | `read-book-toc` |
| 4c | locate pages | per book, in parallel (`asyncio.gather`) | Proposes PDF page ranges for each cited reading ("excerpt proposals"). If printed page numbers don't line up, it reads sample pages to compute the offset. | `locate-reading-pages`, `read-page-offset` |
| 5 | **Teacher review** | UI | Teacher approves, rejects or edits each proposal. Manual excerpts: `POST .../excerpts` (any PDF page range). Approved excerpts become virtual files `excerpt_ref(course, id)` attached to the session. | none |
| 6 | **Vision transcription** (background) | each approval calls `transcribe_books` | `keep_transcribing` finds pages of approved excerpts where `loses_text()` is true (garbled formulas/matrices, or no text) and sends each page as a one-page PDF to a vision model. Result is Markdown + LaTeX, cached per page by `model#PROMPT_VERSION`. 4 pages in parallel; a request that arrives mid-job reruns once afterwards (`AGAIN`). | `transcribe-page` (`notes_vision_model`, `google/gemini-3.7-flash`, effort low) |
| 7 | **Generate notes** | `POST /courses/{c}/notes` (whole course), `/sessions/{s}/notes` (one lecture), `/notes/queue` (all lectures without a note) | Worker pipeline, section 3. | many |
| 8 | **Edit / review** | UI | Manual edits, restore, teacher approval, AI suggestions, "verify this topic", renders. Section 4. | only suggestions and verify |

Steps 1 to 6 happen before any notes exist. Step 6 starts automatically on approval so the pages are ready before generation.

## 3. The notes generation pipeline (worker `run_notes`)

`worker/notes.py::run_notes` runs as one asyncio task per course (`ACTIVE` set, one run per course at a time). Lecture runs go through a per-course queue: `lectures.drain` writes one lecture at a time, then the next waiting one.

```
admit/open_run  ─ freeze inputs: provenance.json + inputs.json (sources, chunks) + plan snapshot
      │           (a resumed run must match its fingerprint, otherwise "Start a new run")
      ▼
build_inputs    ─ per mapped material: PDF page text (pypdf) or vision transcript → chunks of ≤1400 chars
      │           chunk id = <sha8>-p<page>-<n>; adds printed-page labels; records "skipped" warnings
      ▼
plan_course  ── up to `notes_plan_rounds` (3) rounds ─────────────────────────────────────
      │   LLM  draft-course-plan  (planner)  → CoursePlan: sections, topics, objectives,
      │                                         success criteria, prerequisites, key terms,
      │                                         notation, terminology
      │   LLM  check-coverage     (coverage) → CoverageReview; stops when no blocking issues
      │   code check_references  (bad prerequisite/source ids → blocking issues)
      │   lecture mode: exactly 1 section, 1–4 topics; course notation sheet is binding
      ▼
topic_notes   ─ one job per topic, `notes_concurrency` (4) at a time; finished topics are reused on resume
      │   generate_topic(topic):
      │     1. candidates_for   code: BM25 over the topic's own sources first (whole reading if short),
      │                         then ≤8 chunks from other sources; up to 24 + 8 candidates
      │     2. select_evidence  LLM select-evidence (selector, low effort): role + relevance 1–5, ≤16 items
      │     3. no evidence → TopicNote(status="no_evidence"), done
      │     4. synthesize       LLM synthesize-topic (writer): blocks with citations to evidence ids
      │     5. verify loop      LLM verify-topic (verifier, high); if `escalate`, repeat with the escalation model
      │                         revise-topic (writer) on major issues; up to `notes_revision_rounds` (2) revisions;
      │                         from round 2 the escalation model verifies
      │     6. status "verified" or "unresolved" (+ open_issues, structure gaps from code)
      │   a failed topic is stored as status "failed" and does not stop the others
      ▼
collect + harmonize ─ topics in plan order; LLM harmonize-notes (consistency model), batches of 6 topics:
      │                  block-level edits only (notation, repetition, cross-references, ordering);
      │                  `preserves_content` rejects edits that drop formulas, labels or citations;
      │                  every changed topic is re-verified (verify-harmonized-topic[-escalated])
      ▼
notes.json ──► render_notes_outputs (Quarto, no model): full-course HTML + notes.qmd,
               per-topic HTML + PDF, artifacts.json manifest. Failed renders become warnings, not failures.
      ▼
status = done  (lecture runs also extend the course-wide notation sheet)
```

### Models by role (`NotesModels`, env-overridable)

| Role | Default | Effort | Used for |
|---|---|---|---|
| planner | `openai/gpt-6.1-sol` | medium | draft-course-plan |
| coverage | same as planner | high | check-coverage |
| selector | `openai/gpt-6-luna` | low | select-evidence |
| writer | `google/gemini-3.7-flash` | medium | synthesize/revise topic, suggestions |
| consistency | same as writer | medium | harmonize-notes |
| verifier | `openai/gpt-6-luna` | high | verify-topic (all verification) |
| escalation | `openai/gpt-6.1-sol` | high | second verification when the verifier is unsure |
| vision | `google/gemini-3.7-flash` | low | page transcription |
| default | `google/gemini-3.1-flash-lite` | n/a | syllabus, book matching, TOC, page ranges |

Writer (Google) and verifier (OpenAI) are different vendors by default. Each topic's record stores which verifier model ran.

### Every LLM call (`step` names)

`extract-reading-plan`, `match-books`, `read-book-toc`, `locate-reading-pages`, `read-page-offset`, `transcribe-page`, `draft-course-plan`, `check-coverage`, `select-evidence`, `synthesize-topic`, `revise-topic`, `verify-topic`, `verify-topic-escalated`, `harmonize-notes`, `verify-harmonized-topic[-escalated]`, `suggest-blocks`, `verify-suggestion[-escalated]`, `verify-topic-manual[-escalated]`.

### How the LLM layer works

- `worker/llm.py::ask()` is the only entry point: JSON-schema response format (`strict: true`, `$ref`s inlined), `provider.require_parameters`, Pydantic validation of the answer.
- Errors map to HTTP 504 (timeout) and 502 (provider failure or invalid output). **There are no retries** (see issues).
- Clients: 120 s timeout for request-scoped calls, 600 s for background jobs (`LONG_TIMEOUT`), 15 s connect.

## 4. After generation: the editing and verification loop

All of this is stored as **immutable revisions** per run; every change is a new revision, checked against `base_revision` (optimistic concurrency, `RevisionConflict` on mismatch).

| Action | Endpoint (API → worker) | Model? |
|---|---|---|
| Edit a topic's blocks | `PATCH .../topics/{t}` → `/notes/revise` | no |
| Restore an earlier revision | `.../revisions/{r}/restore` | no |
| Teacher approval of a topic | `.../topics/{t}/approval` → `/notes/approval` | no (approval is bound to a content fingerprint and sources) |
| Re-render a revision (html, pdf, docx) | `.../render` → `/notes/render` | no (Quarto; `polish_docx` keeps native OMML equations) |
| AI suggestion for chosen blocks | `.../suggestions` → `/notes/suggestions` | yes: `suggest-blocks` then `verify-suggestion`; stored as a proposal; nothing changes until **Apply** (origin `ai`) |
| Verify this topic | `.../topics/{t}/verify` → `/notes/verify` | yes: `verify-topic-manual`; the result is saved as a metadata revision |
| Upload a figure | `POST .../assets` | no |

Suggestion and verification jobs are persisted before they are scheduled. On restart the worker marks all unfinished jobs and runs as failed and the user starts them again: `fail_interrupted`, `fail_interrupted_jobs`, `fail_interrupted_renders`, `drop_queues`.

## 5. What is running right now, and state

| Process | In-memory state | On disk |
|---|---|---|
| worker | `notes.ACTIVE` (one run per course), `lectures.QUEUES`, `STOPPING`, `TASKS`, `vision.ACTIVE/AGAIN/LOCKS` | `.worker.lock` |
| Per course | none | `plan.json`, transcript, book indexes, text/transcript caches, `queue.json` |
| Per run | none | `run.json` (status, log, warnings, models), `provenance.json`, `inputs.json`, `plan.json` + `plan/draft-N.json`, `plan/review-N.json`, `topics/<id>/{evidence,draft-N,verification-N,note}.json`, `notes.json`, `artifacts.json`, revisions, suggestions, render jobs |

A run's progress is visible in `run.json` (`topics_done/topics_total`, `log`). **No background process runs between jobs.** After a restart nothing continues by itself; a stopped or failed run is resumed manually (`resume`) and reuses finished topics.

**Stop** (`/notes/stop`) cancels the run's asyncio task, clears the queue, and keeps finished topics. Nothing half-written is published.

## 6. Safeguards (good)

- **Frozen inputs:** a run reads only its own `inputs.json`. A resume with changed provenance is refused.
- **Citation-grounded writing:** every block must cite evidence ids. The verifier checks that citations actually support claims, and unsupported claims are a major issue.
- **Deterministic checks:** `structure_gaps`, `evidence_gap`, `validate_references`, and `preserves_content` after harmonization.
- **Evidence gaps stay visible** as `open_issues` or `no_evidence`. The prompts forbid inventing definitions, sources or pages.
- **Two-tier verification:** a stronger escalation model is used for hard proofs, conflicts or when unsure.
- **Atomic writes** for caches (`atomic_json`); vision transcripts are saved page by page, so a stopped job keeps what it paid for.

## 7. Issues and risks found

| # | Severity | Issue | Where |
|---|---|---|---|
| 1 | High | **No retries or backoff on OpenRouter.** One timeout, 429 or provider error fails the call; a failed topic is stored as `failed` and the run only warns. A whole planning call failing fails the run. | `worker/openrouter.py`, `worker/llm.py` |
| 2 | High | **State is files only, behind one worker lock.** No horizontal scaling, and no multi-user isolation beyond directory names. Course ids are `local` or digits. | `worker/main.py` lifespan, `routers/*` |
| 3 | High | **No cost or usage tracking.** Token usage is returned (`Completion.usage`) but dropped. With Langfuse removed there is no tracing, cost limits or per-run cost. | `worker/openrouter.py`, `4ae732c` |
| 4 | Medium | **Retrieval is lexical only (BM25).** A syllabus in Ukrainian with English books depends on the planner writing `key_terms` in both languages; no embeddings, so paraphrases are missed. | `worker/sources.py::Retriever` |
| 5 | Medium | **Topic verification can't catch what the evidence omits.** The verifier sees only the chosen evidence (≤16 chunks), so a wrong-but-cited claim can pass if the selector missed a contradicting passage. | `worker/topics.py` |
| 6 | Medium | **Harmonization can leave a topic "unresolved" or stale on a verifier outage.** It adds a generic major issue instead of failing. The topic's text may already be edited. | `worker/composition.py::recheck_topic` |
| 7 | Medium | **Vision transcripts are a trust gap.** A vision model's output is treated as source text for later citation and verification; a misread formula is then "supported by evidence". | `worker/vision.py`, `sources.build_inputs` |
| 8 | Low | **No prompt-injection guard.** None of the prompts on `main` tells the model to treat excerpts as data and ignore instructions inside them (the `engine-reset` prompts did). Readings come from teacher-uploaded files and Moodle pages. | `worker/topics.py` prompts |
| 9 | Low | **The 4 parallel topics times several rounds of calls can hit provider rate limits**, and with no retry (issue 1) this surfaces as failed topics. Models are named `gpt-6.1-sol`, `gemini-3.7-flash` etc.; a renamed or retired model id fails at runtime, not at startup. | `worker/config.py`, `worker/models.py` |
| 10 | Low | **Background tasks die with the process.** `BackgroundTasks` runs inside uvicorn; a deploy or crash mid-run leaves `running` runs that are only failed at the next worker start. | `worker/main.py` |
| 11 | Low | **Stale docs/config:** `render.yaml` deploys the branch `notes-generation-engine`; README still lists only syllabus transcription for `OPENROUTER_*` although the worker has many roles. | `render.yaml`, `README.md` |

## 8. What is not on `main` (so you don't confuse the two codebases)

Your local `engine-reset` branch is a **separate, unmerged rewrite**: a `deepagents` orchestrator with `chunk-analyst` and `quarto-writer` subagents, an in-memory vector store, Aurora PostgreSQL + S3 for courses, and an offline stub model. None of that is on `main`. `main` has no deepagents, no Aurora/S3 and no vector store. See the earlier audit of that branch for details; the two designs have not been reconciled.
