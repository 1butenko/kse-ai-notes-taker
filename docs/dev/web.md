# Web app (Next.js)

The web app (`web/`) is a Next.js App Router app with TypeScript, Tailwind and shadcn/ui (`base-nova` style on Base UI). Teachers sign in with Google (Auth.js, KSE accounts only), manage courses and lectures, and read or edit the lecture notes. It runs as the `web` service in Docker Compose (port 3000). Read `web/AGENTS.md` and the Next.js guide in `web/node_modules/next/dist/docs/` before writing Next.js code.

## Layout

| Path | What it holds |
|---|---|
| [src/auth.ts](../../web/src/auth.ts), [src/proxy.ts](../../web/src/proxy.ts) | Auth.js setup (`AUTH_ALLOWED_DOMAINS`); sends signed-out visitors to `/sign-in` |
| [src/lib/dal.ts](../../web/src/lib/dal.ts), [api-token.ts](../../web/src/lib/api-token.ts) | `verifySession`, and the signed API call from the server |
| [src/app/api/[...path]/route.ts](../../web/src/app/api/%5B...path%5D/route.ts) | Browser door to the API: forwards `/api/*` with a short-lived token, streaming |
| [src/lib/api.ts](../../web/src/lib/api.ts) | Typed API client, path helpers, `ApiError` (with `detail`) |
| [src/app/(dashboard)/](../../web/src/app/(dashboard)/) | Signed-in shell (`layout.tsx`: app bar) |
| `(dashboard)/(page)/` | Pages in the centred column: `/`, `/courses/[course]`, `/lectures/[course]/[session]`, `/account` |
| `(dashboard)/lectures/[course]/[session]/visual/[[...run]]` | Full-width notes viewer |
| `(dashboard)/lectures/[course]/[session]/edit` | Full-width notes editor |
| `(dashboard)/dev/notes` | Development only: viewer with fake data (`public/dev/sample-notes.html`) |
| [src/components/ui/](../../web/src/components/ui/) | shadcn components; add more with `npx shadcn@latest add <name>` |
| `src/components/course`, `dashboard`, `account` | Course, lecture and account screens |
| [src/components/lecture-notes/](../../web/src/components/lecture-notes/) | Notes viewer, polling hooks, and the editor |
| [src/lib/qmd/](../../web/src/lib/qmd/) | Quarto body ⇄ editor nodes (`convert.ts`), ids, citations, attrs; vitest tests and `fixtures/*.qmd` |

## How it works

- **Viewer.** `/visual` shows the lecture's newest published notes in a sandboxed iframe (`visual-notes-viewer.tsx`); there is no version picker. `visualNotesPath(course, session, saving)` takes the run of a save being rendered and shows its progress until it is published. `siteUrl` adds `?v=2` to `index.html` so browsers drop the old immutable copy.
- **Editor.** `/edit` loads `NotesEditorLoader`, which opens the newest published version with `getLectureNotesSource`. The body is parsed to Plate nodes by `parseQmd` and written back by `serializeQmd`. Anything the parser can't place is kept verbatim in a `qraw` node, so a save never drops text.
- **Save.** `saveLectureNotesEdit` posts `{body, assets}`. A 422 `ApiError` carries `NoteIssue[]` (`line`, `message`). On 202 the page goes to the viewer, which polls the new run. An unsaved edit is kept in `localStorage` (`editor/draft.ts`).
- **Editor files** (`components/lecture-notes/editor/`):

| File | Holds |
|---|---|
| `notes-editor.tsx` | The editor, toolbar, save |
| `plugins.tsx`, `blocks.ts` | Plate plugins and the block types |
| `quarto-nodes.tsx`, `markdown-nodes.tsx`, `equation-nodes.tsx` | Callouts, theorems, tabs, figures, diagrams and equations edited in place |
| `insert-menu.tsx` | `/` menu |
| `inline-pickers.tsx`, `references.ts` | `@` menu: cite a reading or refer to a numbered block |
| `selection-toolbar.tsx` | Toolbar over selected text |
| `block-draggable.tsx`, `block-list.tsx` | Drag handles and lists |
| `diagram-preview.tsx` | Graphviz/Mermaid previews |
| `notes-editor.css` | Draws the editor like the published page; mirrors `lecture-notes.css` and the Quarto theme |

## Interfaces

- Scripts: `npm run dev | build | lint | test` (vitest, `src/**/*.test.ts`), `npm run test:e2e:notes` (`e2e/notes/stack.mjs`).
- In Docker the dev server runs with `--webpack` and `WATCHPACK_POLLING=true` (see `compose.yaml`) so file edits on a Windows host are seen.
- Editor libraries: Plate (`@platejs/*`), `@viz-js/viz`, KaTeX.

## Conventions and gotchas

- Build UI from shadcn components; style with theme tokens (see `CLAUDE.md`).
- The published page's look lives in `api/app/note_taker/lecture_notes/templates/lecture-notes.css`. When it changes, update `notes-editor.css` to match.
- After adding npm packages, rebuild the container: `docker compose up -d --build -V web`.
- The `(page)` route group exists so the notes viewer and editor can fill the whole width; put a normal page under `(page)`.
