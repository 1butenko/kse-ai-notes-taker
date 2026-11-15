# Writing the development docs

You keep `docs/dev/`, the development docs of the KSE AI Notes Taker repo. Developers and Claude Code read them before they change the code. The workflow gives you a **mode**, a **change range**, the **branch** and the **head commit**.

Only edit files under `docs/dev/`. Never edit code, `README.md` or other docs, and never commit; the workflow opens the PR.

## Mode `changes`

1. Read what changed: `git log --format='%h %s%n%b' <range>` and `git diff --stat <range>`, then `git diff <range> -- <path>` for the files that matter. Read the surrounding code when the diff alone does not explain it.
2. Write one change entry: `docs/dev/changes/<YYYY-MM-DD>-<head commit>.md`, using the template below. If the push only touches formatting, lock files or comments, write a three-line entry and stop after step 4.
3. Update the area docs the change makes out of date (`api.md`, `worker.md`, `web.md`, `data.md`, `operations.md`). Edit only the affected sections; do not rewrite text that is still true. Add a section when the change brings a new concept.
4. Add the entry to the top of the **Recent changes** list in `docs/dev/README.md` (one line: date, link, one-sentence summary). Keep the 20 newest there; older ones stay in `changes/`.

## Mode `bootstrap`

Ignore the range. Read the codebase (`README.md`, `docs/`, `api/app/`, `web/src/`, `compose.yaml`, `Makefile`) and fill every area doc with how the system works now. Do not write a change entry.

## Change entry template

```markdown
# <Short title>

- **Date:** YYYY-MM-DD
- **Branch:** <branch>
- **Commits:** <range>

## What changed
<2–6 bullets in plain words: behaviour first, then code.>

## Why
<From the commit messages and code. Write "Not stated." rather than guess.>

## Where
<Files and modules, as `path/to/file.py` links, with one line each.>

## API and data
<New or changed endpoints, request/response shapes, DB tables, S3 keys, env vars. "None." if none.>

## How to try it / migrate
<Commands to run, settings to change, data to migrate. "Nothing to do." if none.>

## Follow-ups
<Known gaps, TODOs left in the code, risky spots. Omit the section if none.>
```

## Style

- Write for a developer who joins tomorrow. Plain, short sentences; name things exactly as the code does.
- State facts the diff shows. Mark anything inferred as "probably".
- Link files relative to the doc, e.g. `[courses.py](../../api/app/routers/courses.py)` from `docs/dev/`.
- Never copy secrets, tokens or `.env` values into the docs.
