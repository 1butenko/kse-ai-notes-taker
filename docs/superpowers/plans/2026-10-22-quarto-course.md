# Книга курсу та експорт — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Implement checkbox tasks after their dependencies; this document is a plan, not a deployment request.

**Goal:** Експортувати погоджену ревізію у Word і читати весь курс як книгу з пошуком, перевіривши повний цикл доопрацювання.

**Architecture:** Word та Quarto Book споживають той самий immutable snapshot, що HTML/PDF. Книга — похідний артефакт однієї ревізії з контрольованим набором файлів; зовнішня публікація не потрібна.

**Tech Stack:** Quarto DOCX/Book, існуючий revision renderer, FastAPI file responses, Next.js, pytest; мінімальний браузерний smoke test за потреби.

**Spec:** [Специфікація](../specs/2026-10-22-quarto-notes.md), [загальний план](2026-10-22-quarto-notes.md).

## Global Constraints

- Українська й англійська; джерела й IDs збережені; виходи прив'язані до ревізії.
- Книга та пошук містять конспект, а не приватні підручники або AI-логи.
- Зберігається чинний повний PDF і PDF окремої теми; Word не має перезаписувати зміст конспекту.
- Усі глобальні вимоги специфікації застосовуються повністю.

## Review Focus

- Українська й матриці в Word — читабельні та редаговані формули (P3.1).
- Дві теми з однаковим title — окремі URLs за topic IDs (P3.2).
- Пошук індексує стару або іншу ревізію — нова книга має власний узгоджений індекс (P3.2).
- Матеріал із попередженням/без evidence — статус видимий також у книзі (P3.2).
- Після save й restore UI показує старий PDF як новий — smoke перевіряє revision labels та URLs (P3.3).

## Файли та відповідальності

| Файл | Дія й відповідальність |
|---|---|
| `api/app/worker/quarto.py`, `api/app/worker/revisions.py` | Додати DOCX до renderer і jobs |
| `api/app/worker/course_book.py` | Створити builder проєкту Quarto Book із snapshot |
| `api/app/routers/notes.py`, `web/src/lib/api.ts` | Видача DOCX та revision-scoped book assets |
| `web/src/components/preview/notes-preview.tsx` | Команди Word / Книга курсу |
| `api/tests/test_notes_exports.py`, `test_course_book.py` | Створити тести експорту й індексації |
| `api/tests/fixtures/notes/quality-course.json` | Створити синтетичний контрольний документ |
| `web/e2e/notes-workflow.spec.ts`, `web/playwright.config.ts` | Створити мінімальну браузерну перевірку основного workflow |
| `web/package.json`, `web/package-lock.json` | Додати тільки потрібний dev test runner |
| `README.md` | Описати edit/render/history/export і встановлення test tools |

## P3.1 — Word-експорт

**Залежності:** P2.3.
**Файли:** modify renderer/revisions, notes router, api.ts, preview; create `api/tests/test_notes_exports.py`.
**Interfaces:** використовувати вже визначений `RenderFormat='docx'` і revision artifact routes; `RenderedArtifact.path` — відносний шлях в artifacts root. Public download: `application/vnd.openxmlformats-officedocument.wordprocessingml.document`. Спочатку повний конспект; topic DOCX використовує той самий topic artifact contract.

- [ ] Додати `test_docx_export_uses_requested_revision`, `test_docx_export_has_no_model_calls`, `test_failed_docx_keeps_html_and_pdf`. Assert revision точно збігається із запитом, LLM calls == 0; DOCX failure не змінює стан успішних HTML/PDF.
- [ ] Запустити `cd api && uv run pytest tests/test_notes_exports.py -v`; очікувати FAIL на недоданому export path.
- [ ] Додати `quarto render ... --to docx --no-execute` для форматного QMD; зберегти citations і формули. Експорт запускати на вимогу, через наявну job, без обов'язкової генерації DOCX після кожного save.
- [ ] UI показує «Завантажити Word» для вибраної ревізії; queued/error/ready і retry. Старий файл не видається як новий. Для print layout використати штатний Word output; reference-doc вводити лише якщо візуальна перевірка доведе його потребу.
- [ ] Pytest: PASS. Відкрити реальний DOCX у Word або LibreOffice: перевірити кирилицю, формули, матрицю, заголовки, таблицю, bibliography й редагованість формул. `npm run lint` і web build: exit 0.
- [ ] Коміт `feat: export note revisions as word documents`.

## P3.2 — Книга курсу з пошуком

**Залежності:** P2.3 та P1.4; P3.1 не блокує цю задачу.
**Файли:** create `api/app/worker/course_book.py`, `api/tests/test_course_book.py`; modify revision jobs, notes router, api.ts, preview.
**Interfaces:** `build_book_project(document: NotesDocument, directory: Path, language: str) -> Path` повертає `_quarto.yml`; `async render_book(directory: Path, revision: int, quarto: str) -> RenderedArtifact`. Розширити `RenderFormat` значенням `book`; це артефакт-каталог з entrypoint `index.html`, окремий від standalone HTML. У всіх спільних моделях використати той самий literal. Dispatcher викликає `render_book` для book-job; `to_quarto` для її глав отримує `target='html'`, а не `book`. API: `GET .../revisions/{revision}/book/{asset_path:path}` і `POST .../revisions/{revision}/render` з `formats:['book']`.

- [ ] Додати `test_book_chapters_follow_document_order`, `test_duplicate_titles_keep_distinct_topic_urls`, `test_book_search_has_only_current_revision_notes`, `test_book_asset_path_cannot_leave_artifact_root`, `test_unresolved_topic_warning_is_visible`. Assert chapter files названі за topic IDs, private filename/chunk text не потрапляє в published files/search corpus.
- [ ] Запустити `cd api && uv run pytest tests/test_course_book.py -v`; очікувати FAIL до builder.
- [ ] Побудувати контрольований Quarto Book: index/title, розділи з topics у порядку документа, спільні bibliography/labels/styles, пошук, previous/next. Відсутні/failed topics отримують сторінку зі статусом, а не непомітно зникають. Міжтемні посилання використовують IDs і правила P1.4.
- [ ] Рендерити окремо у revision staging directory, атомарно публікувати готовий каталог і manifest. Дозволяти видачу лише опублікованих assets у межах book root; шлях через `..` або symlink назовні відхиляти. Книга містить тільки погоджений конспект, не inputs/retrieved/prompts.
- [ ] Додати «Книга курсу» у preview із номером ревізії. Повний PDF залишається окремим форматом. Зміна теми робить книгу попередньої ревізії видимо неактуальною; перебудова використовує один snapshot для всіх глав та індексу.
- [ ] Pytest: PASS. На реальній книзі знайти український термін пошуком, перейти в результат, між двома темами й до джерел; відкрити із застосунку, перевірити ресурси й search assets за revision-scoped URLs.
- [ ] Коміт `feat: add revision scoped course books with search`.

## P3.3 — Повний сценарій та якість результату

**Залежності:** P2.4, P3.1, P3.2.
**Файли:** create контрольну fixture, E2E spec/config; modify `web/package.json`, lockfile, README. Приклад JSON має відповідати актуальним shared models, а не дублювати альтернативну схему.
**Interfaces:** додати web script `test:e2e:notes`; API fixtures використовують наявні in-process worker/mock LLM для backend-тестів. Браузер запускається проти окремого локального test stack із синтетичним uploads root, без production ключів або даних.

- [ ] Створити fixture з двома темами, українськими й англійськими фрагментами, означенням, доведенням, прикладом, матрицею, індексами, довгою формулою, таблицею, рисунком, bibliography, crossrefs і неперевіреним блоком. Додати синтетичний `api/tests/fixtures/notes/figure.png` як ресурс рисунка. Окрема legacy fixture перевіряє старий JSON.
- [ ] Додати мінімальний Playwright dev setup й `notes-workflow.spec.ts`: HTML → edit → save → нова ревізія → artifacts ready → history → restore; друга перевірка AI reject/apply; третя Word download/book search. Не тестувати внутрішні React state або окремі CSS класи.
- [ ] Перед реалізацією відсутніх інтеграцій запустити `cd web && npm run test:e2e:notes`; зафіксувати конкретні поведінкові FAIL. Доповнити тільки пропущені інтеграції. Не підміняти всі format jobs успіхом: окрема перевірка використовує справжній Quarto.
- [ ] Запустити один повний набір: `make test`, `make lint`, `cd web && npm run build`, `cd web && npm run test:e2e:notes`; очікувати exit 0. Browser dependencies встановити за documented setup; відсутність browser/CLI не рахувати PASS.
- [ ] Візуально перевірити HTML на 390 px/desktop, усі сторінки контрольного PDF, DOCX у доступному office viewer та книгу з пошуком. Немає обрізаних формул, зниклих посилань чи неправильної ревізії; зафіксувати фактичні результати й виправити дефекти.
- [ ] README: описати базову гілку, структуру ревізій, commands render/retry, межі AI-перевірки, роботу без OpenRouter, відновлення після render failure і запуск E2E. Показати наскрізний сценарій користувачу.
- [ ] Коміт `test: verify notes editing and multi format publishing`.

## Готовність усього обсягу

- [ ] Єдина структура теми й callouts показані на контрольному курсі.
- [ ] Формули, рисунки, таблиці, crossrefs і citations працюють у HTML/PDF; Word перевірений окремо.
- [ ] Ручні зміни не потребують LLM, не губляться після reload/resume, доступні історія/diff/restore.
- [ ] AI змінює тільки погоджений scope, має нову перевірку, застосовується після перегляду й перевірки базової ревізії.
- [ ] Книга має порядок тем, попередження, пошук і переходи; не містить приватних вихідних матеріалів.
- [ ] Збої рендерингу, конфлікти вкладок і перезапуск worker перевірені; попередні дані доступні.
