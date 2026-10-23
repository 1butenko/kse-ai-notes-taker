# Публікація конспектів — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Execute checked tasks in dependency order; do not begin implementation before the requested planning handoff is complete.

**Goal:** Показувати структуровані конспекти у HTML та PDF з коректною математикою, джерелами й навігацією.

**Architecture:** Наявна модель конспекту розширюється сумісно. Форматування змісту відділяється від запуску Quarto; API та UI використовують опис доступних артефактів. Кожна задача розвиває наявний шлях генерація → worker → файл → preview.

**Tech Stack:** FastAPI/Pydantic, Quarto/Typst/MathJax, Next.js/TypeScript, pytest; наявні Docker targets.

**Spec:** [Специфікація](../specs/2026-10-22-quarto-notes.md), [загальний план](2026-10-22-quarto-notes.md).

**Рішення:** [ухвалені архітектурні рішення](../specs/2026-10-23-quarto-notes-decisions.md) обов'язкові для виконання; вони уточнюють цей план.

## Global Constraints

- Python >=3.12; мови `uk` та `en`; базова гілка `notes-generation-engine`.
- Старі документи та PDF/QMD URL залишаються доступними.
- Основне джерело змісту — `NotesDocument`; PDF — Typst; HTML — MathJax.
- Глобальні вимоги специфікації застосовуються повністю.

## Review Focus

- Старий JSON без мови та schema version — завантажується без втрати IDs (P1.1).
- Quarto відсутній або завис — зрозуміла помилка й збережений QMD, процес завершений (P1.2).
- MathJax і Typst по-різному обробляють формули — окремі виходи з незміненого тексту (P1.2–P1.3).
- Посилання на тему поза standalone PDF — явне посилання на повний конспект, без dangling reference (P1.4).
- Відсутній доказ означення або прикладу — прогалина позначена, зміст не вигадується (P1.5).

## Файли та відповідальності

| Файл | Дія й відповідальність |
|---|---|
| `api/app/notes.py` | Розширити модель: schema version, language, verification freshness; сумісне читання |
| `api/app/worker/render.py` | Зберегти перетворення блоків на QMD; параметризувати цільовий формат |
| `api/app/worker/quarto.py` | Створити runner CLI, результати та помилки окремих форматів |
| `api/app/worker/references.py` | Створити побудову бібліографії, стабільних anchors і перевірку посилань |
| `api/app/worker/templates/notes.css` | Створити контрольований стиль HTML |
| `api/app/worker/notes.py` | Підключити renderer і запис опису артефактів |
| `api/app/routers/notes.py`, `api/app/worker_contract.py` | Видавати артефакти та їх статуси |
| `web/src/lib/api.ts` | Синхронізувати контракти |
| `web/src/components/preview/notes-preview.tsx` | Показувати HTML/PDF, помилки, статуси |
| `api/tests/test_notes.py`, нові `test_notes_rendering.py`, `test_notes_references.py` | Регресія workflow та тести нової поведінки |

## P1.1 — Сумісна модель й збереження мови

**Залежності:** зафіксована базова гілка.
**Файли:** modify `api/app/notes.py`, `api/app/worker/notes.py`, `web/src/lib/api.ts`; test `api/tests/test_notes.py`.
**Interfaces:** `NotesDocument.schema_version: int = 1`, `language: Literal['uk','en'] | None = None`; `TopicNote.verification_stale: bool = False`. Нові документи записуються з `schema_version=2`; старі читаються без переписування. Для старих run мова відновлюється зі збереженого transcript, якщо він доступний; інакше лишається невідомою з явним вибором перед новим рендером.

- [ ] Додати `test_legacy_notes_load_without_losing_ids`: fixture старого JSON читається; список `(topic_id, block.id, citations)` збігається до й після читання. `test_generated_notes_persist_language`: з `Transcript.language='uk'` результат має `language=='uk'`.
- [ ] Запустити `cd api && uv run pytest tests/test_notes.py -k 'legacy_notes or persist_language' -v`; очікувати FAIL на відсутньому полі або незбереженій мові.
- [ ] Додати поля з сумісними defaults, запис мови й синхронні TypeScript типи. Не змінювати зміст або існуючі IDs.
- [ ] Повторити команду: PASS; запустити весь `tests/test_notes.py`: старі сценарії PASS.
- [ ] Переглянути diff і створити окремий коміт `feat: preserve notes language and schema metadata`.

## P1.2 — Один runner для HTML та PDF

**Залежності:** P1.1.
**Файли:** create `api/app/worker/quarto.py`, `api/tests/test_notes_rendering.py`; modify `api/app/notes.py`, `api/app/worker/render.py`, `api/app/worker/notes.py`, `api/Dockerfile`.
**Interfaces:** у спільному `api/app/notes.py` визначити `RenderFormat = Literal['html','pdf','docx']` та `RenderedArtifact(format: RenderFormat, path: str, revision: int, status: Literal['ready','failed'], error: str | None, topic_id: str | None=None)`. `path` відносний до artifacts root; worker проставляє topic_id для topic output. Runner: `async render_document(sources: dict[RenderFormat, Path], output_dir: Path, revision: int, quarto: str) -> list[RenderedArtifact]`. Для кожного формату sources містить окремий підготовлений QMD; виходи будуються в окремих staging-підкаталогах. `to_quarto(document, language, target: RenderFormat='pdf') -> str`; той самий target додати до `topic_to_quarto`. `pdf` у runner мапиться на CLI `--to typst`.

- [ ] Додати `test_render_html_and_pdf_without_llm`: fake CLI створює два файли; `assert {a.format for a in result if a.status=='ready'} == {'html','pdf'}`; LLM mock має 0 викликів. Додати `test_failed_html_keeps_successful_pdf` і `test_renderer_timeout_kills_and_reaps_process`.
- [ ] Запустити `cd api && uv run pytest tests/test_notes_rendering.py -v`; очікувати FAIL до реалізації runner.
- [ ] Реалізувати runner із наявним timeout 600 s, окремим логом формату, `--no-execute`, контрольованими YAML/resources і завершенням subprocess після timeout. Формувати HTML/Typst QMD окремо: Typst-поправки формул не застосовувати до HTML. Команди отримують список аргументів без shell.
- [ ] Підключити до генерації: записувати `artifacts.json` навіть за часткової помилки; початковий результат позначати `revision=0`. Поки немає ревізій, зберігати наявні `notes.pdf`/topic PDF та їх URL.
- [ ] Повторити pytest: PASS. Доповнити Docker warmup HTML+Typst прикладом українського тексту та матриці; `docker compose build worker` завершується успішно. CLI відсутній — документ залишається з warning, як раніше.
- [ ] Коміт `feat: render notes as html and typst pdf`.

## P1.3 — Читання HTML у застосунку

**Залежності:** P1.2.
**Файли:** create `api/app/worker/templates/notes.css`; modify `api/app/routers/notes.py`, `web/src/lib/api.ts`, `web/src/components/preview/notes-preview.tsx`, `web/src/components/dashboard/notes-stage.tsx`; test `api/tests/test_notes_rendering.py`.
**Interfaces:** `NotesRunView.artifacts: list[RenderedArtifact]` з default `[]`; розширити `notesFileUrl(..., kind: 'pdf'|'qmd'|'html'|'docx')`. Новий `GET /plans/{course}/notes/{run}/topics/{topic}/html`; чинні маршрути лишаються. CSS і локальні зображення включаються через `embed-resources`; для MathJax використовувати штатну доставку Quarto і перевірити її у browser smoke. Повністю автономний HTML без мережі не є обіцянкою цього кроку.

- [ ] Додати `test_html_download_and_unknown_topic`: API віддає `text/html`, неіснуюча тема — 404; старий PDF — 200. Додати `test_html_does_not_include_source_text_outside_notes`: повний підручник не включений у артефакт.
- [ ] Запустити `cd api && uv run pytest tests/test_notes_rendering.py -v`; очікувати FAIL для нового маршруту.
- [ ] Додати видачу HTML та UI-перемикач HTML/PDF. HTML — основний режим, PDF доступний для друку; для legacy run без HTML показувати наявний PDF. Зберегти мобільний вибір теми, Copy link та позначки неперевірених тем.
- [ ] Додати стиль зі змістом, комфортною шириною тексту та горизонтальним прокручуванням широких таблиць. HTML показувати в ізольованому iframe з мінімальними дозволами для MathJax й без доступу до стану батьківського застосунку; перевірити фактичну роботу формул.
- [ ] Pytest: PASS; `cd web && npm run lint && npm run build`: exit 0. Вручну перевірити 390 px та desktop: заголовки, матриця, таблиця, довга формула, перемикання тем і PDF, клікабельний зміст. Не заявляти автоматизацію браузера, поки її не додано.
- [ ] Коміт `feat: add responsive html notes preview`.

## P1.4 — Стабільні посилання та бібліографія

**Залежності:** P1.3.
**Файли:** create `api/app/worker/references.py`, `api/tests/test_notes_references.py`; modify `api/app/worker/render.py`, `api/app/worker/notes.py`.
**Interfaces:** `build_reference_data(document: NotesDocument) -> list[dict]` повертає CSL JSON з ключами `src-{Source.id}`; `reference_id(topic_id: str, block_id: str | None=None) -> str` повертає стабільну `sec-...` мітку; `validate_references(document: NotesDocument) -> list[str]` повертає знайдені некоректні посилання. Мітки формул/рисунків/таблиць у контенті мають префікси `eq-`, `fig-`, `tbl-`; їх валідність і унікальність перевіряються перед рендером.

- [ ] Додати `test_citation_preserves_source_and_printed_page`: evidence page `p. 10` лишається сторінкою 10, не PDF offset; `test_reference_ids_survive_title_edit`: `assert before_id == after_id`; `test_unknown_citation_is_reported`; `test_standalone_topic_links_external_topic_explicitly`.
- [ ] Запустити `cd api && uv run pytest tests/test_notes_references.py -v`; очікувати FAIL до створення helper.
- [ ] Побудувати bibliography з відомих title/метаданих, без вигаданих авторів/років; посилання `[@src-1, p. 10]`. Увімкнути `citeproc: true` для узгодження HTML/Typst. Поточні chunk citations залишаються джерелом зв'язку твердження з evidence.
- [ ] Додати anchors до тем/блоків та нормалізацію міжтемних переходів. Повний документ використовує внутрішні посилання; standalone тема посилається на відповідний HTML topic/full document. Зовнішня формула не лишається unresolved `@eq-...` у topic PDF.
- [ ] Рисунки беруться лише з явних локальних ресурсів конспекту: скопіювати їх у контрольований assets root, перевірити шлях і відповідність caption/fig-ID; забезпечити ті самі ресурси у HTML, Typst та DOCX. Не робити прихованих завантажень з URL, запропонованих моделлю. Додати `test_figure_resource_and_caption_survive_render`.
- [ ] Pytest: PASS. На реальному Quarto перевірити номер формули, таблиці й рисунка, перехід між темами, бібліографію та сторінку в HTML/PDF. Лише після цього замінити старий власний footer цитувань.
- [ ] Коміт `feat: add stable cross references and bibliography`.

## P1.5 — Навчальна структура та повнота теми

**Залежності:** P1.4.
**Файли:** modify `api/app/worker/topics.py`, `api/app/worker/render.py`, `api/app/worker/composition.py`, `api/tests/test_notes.py`.
**Interfaces:** Зберегти `NoteBlock.kind`, `TopicNote.blocks` та існуючий verifier. Додати `topic_structure_issues(note: TopicNote) -> list[str]`; прогалини показувати через існуючі `open_issues`, а не новий паралельний status workflow.

- [ ] Додати `test_topic_without_example_reports_gap_when_objective_requires_one`; `test_structure_does_not_invent_unsupported_definition`; `test_harmonization_preserves_reference_ids_and_citations`. Використати наявні mock OpenRouter та in-process worker, без реальних model calls.
- [ ] Запустити `cd api && uv run pytest tests/test_notes.py -v`; нові assertions спершу FAIL.
- [ ] Оновити writer/verifier prompts: спочатку інтуїція, далі означення/властивості, приклад, підсумок за наявності evidence; відповідність залежить від objectives. Не вимагати теорему в кожній темі. Гармонізація зберігає IDs, формули й джерела.
- [ ] Узгодити callouts й україномовні назви для всіх типів блоків; довгі доведення можна згортати в HTML, у PDF вони повністю доступні. Помітно позначити неперевірені твердження й прогалини evidence.
- [ ] Pytest та `make lint`: PASS. Показати контрольну тему з означенням, прикладом і підсумком у двох форматах; перевірити джерела блоків.
- [ ] Коміт `feat: improve study note structure and evidence gaps`.
