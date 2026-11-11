"""The lecture-notes agent: one lecture's readings in, a visual Quarto page out.

A standalone deep agent (not a subagent of the orchestrator), started from the lecture page. It
reads the lecture's readings from its virtual filesystem, learns Quarto from its skills, writes
`/notes/index.qmd`, renders it with `render_notes` and has a `reviewer` subagent check it. See
`docs/note-taker/lecture-notes.md`.
"""
