# KSE AI Notes Taker

Monorepo: `api/` (FastAPI, Python 3.12, uv; `api/app/worker` is the model-calling worker) and `web/` (Next.js App Router, TypeScript, Tailwind, shadcn/ui). Run everything with `make up` (Docker Compose). Read `README.md` first and `docs/note-taker/` for the AI Note Taker.

## UI: shadcn components only

- Build every UI element from shadcn components (`web/src/components/ui/`) whenever one exists. Never hand-roll a button, input, dialog, select, tabs, tooltip, card, badge, alert, etc. out of raw HTML/Tailwind.
- Missing a component? Add it with `npx shadcn@latest add <name>` (run in `web/`) and then use it. Do not copy shadcn code by hand or write a look-alike.
- Style with the shadcn variants and theme tokens (`bg-background`, `text-muted-foreground`, ...), not hard-coded colors. Use `lucide-react` for icons.
- Use the `shadcn` skill (`.claude/skills/shadcn`) before adding or changing UI. This project uses the `base-nova` style on Base UI (`@base-ui/react`), not Radix; see `web/components.json`.
- Plain HTML is fine only for layout and text (`div`, `main`, `p`, headings) or when no shadcn component fits.

## Next.js

`web/AGENTS.md` applies: this Next.js has breaking changes, so read the guide in `web/node_modules/next/dist/docs/` before writing Next.js code.

## Working here

- Use the project skill `kse-notes-taker` (`.claude/skills/kse-notes-taker`) for commands, layout and conventions.
- Web package manager is npm (`package-lock.json`); the Docker web container needs a rebuild after adding packages: `docker compose up -d --build -V web`.
- Never commit `.env`.
