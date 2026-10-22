# Task 3 report — responsive HTML notes preview

Implemented P1.3 on `feature/quarto-notes` from base `36490b7`.

## Changes

- API exposes full-run and topic HTML with `text/html`, and reads `artifacts.json` into `NotesRunView.artifacts` (default `[]` for legacy runs). Existing PDF/QMD URLs and topic PDF downloads remain usable. The download helper also accepts the planned DOCX format.
- HTML is the default preview where a ready HTML artifact exists; PDF remains selectable for printing and is the fallback for legacy runs. Dashboard reading/topic actions use HTML preview where available. Copy link, mobile topic selection, unverified badges, and existing preview paths are preserved.
- Preview shows text/artifact revisions (initial and legacy revision zero). Artifact mismatch is labeled as an older artifact.
- Server-owned CSS is copied into the renderer's isolated staging directory and embedded by Quarto. It provides comfortable reading width, an in-body contents list visible on mobile, and horizontal table/equation scrolling. The mobile app header wraps the notes title onto its own row.
- Both the HTML HTTP response and the iframe enforce `sandbox allow-scripts` without `allow-same-origin`. CSP disables connections, forms, base URL changes, and unrelated resources; it permits embedded styles/scripts/images/fonts and Quarto's normal MathJax 3 CDN script/fonts. Direct HTML opening retains sandbox isolation.
- Standard Quarto scripts use a server-owned header fallback for document-local, volatile preferences when opaque-origin storage throws. A closure Map replaces only this document's `localStorage`; it does not expose the application's storage. This preserves Quarto behavior under isolation. Coordinated and cross-checked with the controller's book preflight.
- HTML creation-date labels are `Створено` / `Created`, reflecting the saved creation timestamp.

## RED / GREEN

- Before the routes were added, `test_html_download_and_unknown_topic` failed because `/html` returned HTTP 404. The initial source-exclusion fixture also exposed a fixture-model construction error, corrected to use the existing typed Source/EvidenceItem models.
- Added HTTP checks for full/topic HTML MIME, sandbox/security headers, unknown and traversal-shaped topics, legacy full/topic PDF and QMD, artifact metadata, and absent-manifest legacy default.
- Added source-exclusion coverage: private nearby textbook text and selected evidence excerpts do not enter the rendered notes payload. Extended the installed-Quarto test to assert embedded styling, the trusted header, and the Ukrainian creation label.
- `cd api && .venv/bin/python -m pytest tests/test_notes_rendering.py -v`: **13 passed, 1 skipped** without the opt-in Quarto variable.
- `cd api && QUARTO_TEST_BIN=/private/tmp/kse-quarto-1.10.19/bin/quarto TYPST_FONT_PATHS=/private/tmp/dejavu-fonts-ttf-2.37/ttf .venv/bin/python -m pytest tests/test_notes_rendering.py tests/test_notes.py -q`: **46 passed**, including actual HTML/PDF/DOCX rendering. Quarto needed the approved execution context to access its Sass cache.
- Ruff check/format check on touched Python files and `git diff --check`: **pass**.
- `cd web && npm run lint && npm run build -- --webpack`: **exit 0**. Webpack uses the controller-verified baseline because sandboxed default Turbopack encounters OS port restrictions.

## Actual browser/visual validation

Temporary synthetic fixtures and browser tooling live only under `/private/tmp/kse-task3-qa`; no real course/user data was used. API/web ran locally on 8013/3013. A temporary Playwright script used the installed system Chrome, then screenshots were visually inspected. This is a task smoke check, not a checked-in browser automation suite.

- Desktop **1440 × 1000**, mobile **390 × 844**: title, Ukrainian headings, matrix, table, long equation, topic/status display, and format controls are readable. Controller also inspected desktop/mobile screenshots.
- MathJax startup and font loading completed before final screenshots; the full notes contained four rendered MathJax containers. Topic formula rendering was checked after topic navigation.
- Contents links navigate to their headings at both widths; the mobile body contents override is needed because Quarto's runtime otherwise hides its contents list on narrow screens.
- At 390 px the app/body width is 390/390; iframe viewport/body is 364/364. The table is 595 px wide within a 309 px viewport. Both table and long equation successfully scrolled horizontally by 80 px; long equation content was 591 px in a 309 px viewport.
- Desktop topic links and mobile topic selector select the correct topic HTML URL; unresolved badges remain visible. HTML/PDF switching changes the iframe URL correctly. Copy link copies the selected-topic preview URL. A separate legacy run with no HTML/manifest opens PDF and disables HTML.
- Iframe parent DOM access throws `SecurityError`. A parent storage canary is unreadable (`null`) in the document-local preference store. Direct HTML opening cannot read cookies (`SecurityError`) or parent storage. Final browser console/page errors: **none**.

Screenshots:

- `/private/tmp/kse-task3-qa/desktop.png`
- `/private/tmp/kse-task3-qa/mobile.png`
- `/private/tmp/kse-task3-qa/mobile-math.png`
- `/private/tmp/kse-task3-qa/mobile-topic.png`

## Self-review and limits

The additional renderer changes only stage known server assets and supply controlled HTML options; Markdown validation and PDF/Word math handling are unchanged. No dependency or Docker build changes were made. MathJax uses Quarto's normal delivery; fully offline HTML is not promised. Revision creation/editing is subsequent work; this task surfaces available revision metadata and preserves initial/legacy revision zero. PDF printing was checked through format availability and the actual PDF renderer, not an OS print dialog.
