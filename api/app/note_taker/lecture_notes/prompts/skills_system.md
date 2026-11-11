## Quarto skills

You have a library of skills: short guides to writing each kind of Quarto content for lecture notes, based on the Quarto documentation.

{skills_locations}{skills_load_warnings}

**Available skills:**

{skills_list}

**How to use them:**

1. Before you write a kind of content (a diagram, an interactive explorer, a callout, math), find the skill that covers it in the list above.
2. Read the whole skill with `read_file` on its path, with `limit=1000`.
3. Follow its syntax and rules exactly. `render_notes` rejects what the skills do not allow, and the skills' templates are known to render.

Always read `lecture-notes-structure` and `sources-and-faithfulness` before writing.
