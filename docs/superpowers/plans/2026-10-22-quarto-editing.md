# Редагування конспектів — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Execute checkbox steps in dependency order. Execution method is selected at the planning handoff.

**Поточний стан:** P2.1–P2.4 виконано в `feature/quarto-notes`. Чеклісти нижче є початковими завданнями; чинні правила HEAD, блокування run, orphan, jobs, restore і AI зібрані в [рішеннях](../specs/2026-10-23-quarto-notes-decisions.md).

**Goal:** Викладач редагує одну тему, бачить історію й отримує оновлені формати; AI пропонує точкові зміни для перегляду.

**Architecture:** Незмінні знімки ревізій з оптимістичною перевіркою бази. Worker — єдиний власник команд запису та рендерингу; API/UI читають snapshot і стан job. Ручні зміни працюють незалежно від налаштування OpenRouter.

**Tech Stack:** FastAPI/Pydantic, файлові snapshots і `fcntl.flock` для macOS/Linux, існуючий WorkerClient, Markdown/LaTeX редактор на React, pytest.

**Spec:** [Специфікація](../specs/2026-10-22-quarto-notes.md), [загальний план](2026-10-22-quarto-notes.md); попередній результат — P1.1–P1.5.

**Рішення:** [ухвалені архітектурні рішення](../specs/2026-10-23-quarto-notes-decisions.md) обов'язкові для виконання; вони уточнюють цей план.

## Global Constraints

- `NotesDocument` є основним джерелом змісту; `.qmd` не редагується двосторонньо.
- Незмінені IDs та джерела зберігаються; старі run і URL залишаються доступними.
- Ручне збереження та повторний рендер не викликають LLM.
- Старий `verified` не переноситься автоматично на змінений текст.
- Всі глобальні вимоги специфікації застосовуються повністю.

## Review Focus

- Дві вкладки або два процеси пишуть одночасно — один commit, другий 409 (P2.1).
- Resume початкової генерації після ручних правок — ревізії не перезаписуються (P2.1).
- Помилка збереження або рендерингу — попередня ревізія/артефакт доступні (P2.1/P2.3).
- AI-пропозиція створена для старої бази — застосування блокується без втрати чернетки (P2.4).
- Користувач має незбережений текст і переходить на іншу тему — попередження, чернетка лишається (P2.2).

## Файли та відповідальності

| Файл | Дія й відповідальність |
|---|---|
| `api/app/notes_revisions.py` | Створити спільні моделі snapshot/patch, read helpers і транзакційний RevisionStore |
| `api/app/worker/revisions.py` | Створити команди редагування/відновлення, job rendering, startup recovery |
| `api/app/worker/note_suggestions.py` | Створити AI-пропозиції та перевірку цільової теми |
| `api/app/worker/main.py`, `api/app/worker_contract.py`, `api/app/worker_client.py` | Передача команд і background jobs |
| `api/app/routers/notes.py` | Зовнішні revision/edit/render/suggestion endpoints |
| `web/src/components/notes/editor.tsx` | Створити редактор блоків вибраної теми |
| `web/src/components/notes/revision-history.tsx` | Створити історію, diff і відновлення |
| `web/src/components/notes/suggestion-review.tsx` | Створити перегляд/застосування/відхилення AI-змін |
| `web/src/lib/api.ts`, існуючий preview | Контракти, revision-aware URLs і стани |
| `api/tests/test_notes_revisions.py`, `test_notes_suggestions.py` | Створити тести API → worker → filesystem |

## Спільні контракти

У `api/app/notes_revisions.py` визначити:

- `RevisionInfo(revision: int, parent: int | None, created_at: str, origin: Literal['generation','manual','restore','ai'], changed_topics: list[str], restored_from: int | None=None)`.
- `RevisionView(info: RevisionInfo, document: NotesDocument)`.
- `TopicPatch(base_revision: int, blocks: list[NoteBlock])`. Порожній `block.id` означає новий блок: сервер призначає `b-{uuid4.hex}`. Непорожній ID має належати цільовій темі. Переданий список є повним новим порядком її блоків; відсутній старий блок означає видалення.
- `RenderJob(id: str, revision: int, status: Literal['queued','running','done','failed'], formats: list[RenderFormat], errors: list[str])`.
- `EditResult(revision: RevisionInfo, render: RenderJob | None)`.
- `RevisionStore(directory: Path)` з методами `current() -> RevisionView`, `list() -> list[RevisionInfo]`, `read(revision: int) -> RevisionView`, `commit_topic(topic_id: str, patch: TopicPatch, origin: Literal['manual','ai']='manual') -> RevisionView`, `restore(target_revision: int, base_revision: int) -> RevisionView`.

`RenderFormat` і `RenderedArtifact` — ті самі спільні моделі, що у P1.2; не створювати їх повторно. `RevisionConflict` мапиться на 409, невідома тема/ревізія — 404, невалідні IDs/evidence — 422.

Зберігання: `notes/<run>/revisions/<six-digit-revision>/document.json`, `revision.json`, підкаталог `artifacts/`; `head.json` містить поточний номер ревізії. Початковий `notes.json` незмінний і представляє revision 0. Перший запис worker матеріалізує snapshot 0. API read helpers не виконують міграційних записів.

## P2.1 — Ревізії та API зміни теми

**Залежності:** P1.5.
**Файли:** create `api/app/notes_revisions.py`, `api/app/worker/revisions.py`, `api/tests/test_notes_revisions.py`; modify worker main/contracts/client, notes router, `api/app/worker/notes.py`.
**Interfaces:** контракти вище; public `GET /plans/{course}/notes/{run}/revisions`, `GET .../revisions/{revision}`, `PATCH .../topics/{topic}` з `TopicPatch`, `POST .../revisions/{revision}/restore` з `{base_revision}`. Worker команди: `POST /notes/revise`, `POST /notes/restore`; `WorkerClient.revise_notes(...) -> EditResult`, `restore_notes(...) -> EditResult`. `GET run` додає `current_revision: int=0` та повертає актуальний structured document.

- [ ] Додати `test_edit_one_topic_preserves_other_topics_and_sources`, `test_old_run_imports_as_revision_zero`, `test_two_writers_have_one_conflict`, `test_resume_preserves_edited_revision`, `test_changed_topic_loses_old_verification`, `test_foreign_block_or_chunk_id_is_rejected`. Основні assertions: `other_topic_after == other_topic_before`; `second.status_code == 409`; зміна одного блоку не змінює IDs решти; змінена тема має `status=='unresolved'` і `verification_stale is True`.
- [ ] Запустити `cd api && uv run pytest tests/test_notes_revisions.py -v`; очікувати FAIL для нових endpoints/сховища.
- [ ] Реалізувати store: під файловим lock прочитати HEAD, перевірити base, deep-copy document, валідувати scope/IDs/evidence, записати snapshot через staging, атомарно змінити HEAD. Незавершений snapshot не стає current. Тест конкуренції використовує окремі процеси, а не тільки asyncio tasks.
- [ ] Змінювати тільки завершений run; поки генерація running — 409. Ручне збереження не вимагає OpenRouter. Restore створює новий snapshot, не пересуває HEAD назад і не видаляє історію; змінені теми потребують нової перевірки.
- [ ] Підключити API → WorkerClient → worker. У цьому кроці `EditResult.render=None`; API лишає попередні артефакти з їх ревізією. Resume за наявності editorial revisions відхиляти 409 з поясненням створити новий run; не змінювати початкову генерацію непомітно.
- [ ] Pytest: PASS; `cd api && uv run pytest tests/test_notes.py -v`: PASS. Перевірити з mock LLM, що save/restore не роблять model calls.
- [ ] Коміт `feat: add immutable notes revisions and scoped edits`.

## P2.2 — Редактор, diff та відновлення

**Залежності:** P2.1.
**Файли:** create editor/history компоненти з карти файлів; modify `web/src/lib/api.ts`, `web/src/components/preview/notes-preview.tsx`.
**Interfaces:** `saveNotesTopic(course, run, topic, patch: TopicPatch): Promise<EditResult>`, `listNotesRevisions(...): Promise<RevisionInfo[]>`, `getNotesRevision(..., revision): Promise<RevisionView>`, `restoreNotesRevision(..., revision, baseRevision): Promise<EditResult>`. Редактор зберігає `base_revision` разом із локальною чернеткою.

- [ ] Скласти контрольний UI-сценарій: змінити формулу, додати/переставити блок, змінити citations зі списку evidence, зберегти; відкрити дві вкладки й отримати 409 у другій; відновити попередню версію; перейти з незбереженою чернеткою. Зафіксувати очікування до реалізації.
- [ ] Додати editor для title/content/kind/citations блоків; нові блоки передають порожній ID. Зберігати чернетку в sessionStorage за course/run/topic/base_revision; UI-позначки описують збережений і незбережений стан без обіцянки live-render чернетки.
- [ ] Додати історію зі змістовним порівнянням блоків за IDs: додано, видалено, змінено; показувати старий/новий текст та citations. Відновлення викликає API з поточною базою. Конфлікт показує актуальну ревізію й зберігає локальний текст для перенесення правок.
- [ ] Показувати втрату актуальності перевірки. Додати попередження перед перемиканням теми/виходом із незбереженими правками; не скидати стан редактора через background polling.
- [ ] Виконати контрольний сценарій, `cd web && npm run lint && npm run build`: exit 0. Дані після reload відповідають API; історія й restore видимі в новій вкладці.
- [ ] Коміт `feat: add topic editor and revision history`.

## P2.3 — Повторний рендер збереженої ревізії

**Залежності:** P2.2, runner P1.2.
**Файли:** modify `api/app/worker/revisions.py`, worker main/contracts/client, notes router, api.ts і preview; tests `api/tests/test_notes_revisions.py`.
**Interfaces:** `enqueue_render(directory: Path, revision: int, formats: list[RenderFormat]) -> RenderJob` записує queued job; `async render_revision(directory: Path, job_id: str, settings: WorkerSettings) -> RenderJob` виконує збережену job і повертає кінцевий стан. Public `POST .../revisions/{revision}/render` з `{formats}`, `GET .../render-jobs/{job}`, `GET .../revisions/{revision}/artifacts/{kind}` і `GET .../revisions/{revision}/topics/{topic}/artifacts/{kind}`. `GET run` додає `display_revision: int | None`; явні URL snapshot — канонічні, legacy URL залишаються aliases.

- [ ] Додати `test_manual_edit_renders_without_model_calls`, `test_old_render_cannot_replace_new_head`, `test_failed_render_keeps_previous_artifact`, `test_worker_restart_marks_render_job_failed_and_retry_succeeds`. Assert LLM calls == 0; HTML/PDF manifest містить номер snapshot; completion старої job не змінює HEAD.
- [ ] Запустити `cd api && uv run pytest tests/test_notes_revisions.py -v`; нові render assertions спершу FAIL.
- [ ] Зберігати RenderJob на диску до background launch; save/restore повертає job і запускає HTML+PDF. Job читає тільки immutable snapshot і пише у його artifacts/staging, потім атомарно публікує manifest. Нові ревізії можуть накопичуватися; результат старої job не позначається актуальним для нової. Для тієї самої ревізії серіалізувати jobs під окремим render-lock і зливати manifest за ключем `(topic_id, format)`; повторний Word/book render не видаляє готовий PDF/HTML.
- [ ] На startup маркувати queued/running jobs попереднього процесу failed, зберігати текст і дозволяти явний retry. Відокремити render failure від генерації notes; часткова помилка формату лишає успішні результати. Якщо хоч один запитаний вихід не створений, job отримує `failed`, зі списком errors та успішними артефактами в manifest.
- [ ] UI poll прив'язати до job, показувати current/display revision, pending/error/retry. До готовності нової ревізії показувати попередній файл з явною позначкою його версії. Ручний rerender не викликає LLM, планувальник або harmonization.
- [ ] Pytest: PASS; вручну вимкнути Quarto, зберегти правку, перевірити чернетку/історію/старий PDF; повернути Quarto та натиснути retry. `make test`, `make lint`: PASS.
- [ ] Коміт `feat: rebuild revision artifacts without regenerating notes`.

## P2.4 — Точкові AI-пропозиції та повторна перевірка

**Залежності:** P2.3.
**Файли:** create `api/app/worker/note_suggestions.py`, `web/src/components/notes/suggestion-review.tsx`, `api/tests/test_notes_suggestions.py`; modify worker API/contracts/client, notes router, topics verifier, api.ts і editor.
**Interfaces:** `SuggestionRequest(base_revision: int, topic_id: str, block_ids: list[str], instruction: str)`; `NoteSuggestion(id: str, base_revision: int, topic_id: str, status: Literal['queued','running','ready','failed','applied','rejected'], proposed_blocks: list[NoteBlock], verification: Verification | None, error: str | None)`. Порожній `block_ids` означає всю тему; зміна інших тем заборонена. Public `POST .../suggestions`, `GET .../suggestions/{id}`, `POST .../suggestions/{id}/apply` з `{base_revision}`, `POST .../suggestions/{id}/reject`.

- [ ] Додати `test_suggestion_does_not_change_current_document`, `test_reject_preserves_revision`, `test_apply_stale_suggestion_returns_409`, `test_unknown_evidence_is_rejected`, `test_ai_edits_only_selected_blocks`, `test_new_example_is_inserted_after_selected_block`, `test_unsupported_suggestion_is_not_marked_verified`. Assert HEAD незмінний до apply, citations належать наявному evidence, після apply інші теми рівні попереднім.
- [ ] Запустити `cd api && uv run pytest tests/test_notes_suggestions.py -v`; очікувати FAIL до реалізації.
- [ ] Реалізувати async proposal job через наявний worker/LLM/verifier, використовуючи evidence вибраної теми та registry позначень. Інструкції: пояснити простіше, розширити приклад, уточнити доведення; модель повертає structured blocks. Нові IDs призначає сервер. Незмінені блоки вибраної теми сервер зберігає; вставка дозволена після вибраного блоку, за порожнього scope — будь-де в темі.
- [ ] Зберігати пропозицію й нову перевірку окремо від current. При apply повторно перевіряти base_revision та scope, викликати RevisionStore; попередня перевірка знімається, а статус `verified` можна встановити лише на основі нової успішної перевірки саме застосованого тексту. Major issues залишають `unresolved` і видимі причини.
- [ ] UI показує diff тексту, джерел і verification issues; має Apply/Reject. Apply створює нову ревізію й render job. Конфлікт не застосовує старий результат мовчки. За недоступного OpenRouter — 503 лише AI-команді; ручний editor працює.
- [ ] Pytest: PASS; перевірити сценарії «спростити», «додати приклад», reject і stale apply з mock LLM; `make test`, `make lint`, web build: PASS.
- [ ] Коміт `feat: add reviewed ai suggestions for note topics`.

## P2.5 — Ручне підтвердження викладача та публікація без дисклеймера

**Статус:** заплановано на майбутнє за запитом користувача 2026-10-25; зараз не реалізовувати. P2.1–P2.4 завершені незалежно від цього доповнення.

**Мета:** викладач може переглянути зауваження AI, підтвердити тему та прибрати дисклеймер із документів для студентів. Рішення викладача зберігається окремо від результату автоматичної перевірки.

**Залежності:** існуючі ревізії, History та рендеринг збережених ревізій. Перед реалізацією уточнити специфікацію й контракти; наведені нижче пункти є вимогами майбутньої функції.

- [ ] Додати явну дію «Підтверджено викладачем» для вибраної теми з можливістю відкликати підтвердження. Показувати зауваження до підтвердження, щоб викладач міг свідомо прийняти рішення.
- [ ] Зберігати рішення, його автора, час і за потреби коментар у незмінній історії. Ручне підтвердження не перетворює результат AI на `verified` і не видаляє зауважень чи джерел.
- [ ] Прив'язати підтвердження до конкретного змісту теми та її джерел. Зміна тексту, формул, рисунків або джерел потребує повторного підтвердження; редагування іншої теми не скасовує рішення для незміненої. Окремо визначити поведінку metadata-only перевірок і restore, не допускаючи застосування підтвердження до іншого змісту.
- [ ] Для підтвердженої теми прибирати автоматичний дисклеймер із студентського HTML, PDF, DOCX та книги курсу, включно з повним конспектом і окремими темами. В інтерфейсі викладача зберігати доступ до зауважень AI й показувати окрему позначку ручного підтвердження.
- [ ] Підтвердження та його відкликання використовують наявні захист від конфліктів, історію й jobs рендерингу. Раніше створені ревізії та файли не переписуються; помилка рендерингу зберігає рішення і дозволяє повторну спробу. Ці дії не викликають LLM.
- [ ] Перевірити сценарії: підтвердження теми з `Unresolved`; приховування дисклеймера в усіх форматах; збереження зауважень у History; відкликання; інвалідація після зміни змісту або джерел; дві вкладки; історичні ревізії; retry після помилки Quarto; відсутність додаткових викликів моделі.
