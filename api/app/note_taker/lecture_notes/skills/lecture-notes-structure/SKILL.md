---
name: lecture-notes-structure
description: Use first, for every note. The shape of a lecture page - objectives, a hook, one idea per section with stable ids, recap and key terms - and the Quarto Markdown basics (headings, cross-references, footnotes) the page is built from.
---

# Lecture notes structure

Quarto docs: Markdown Basics (quarto.org/docs/authoring/markdown-basics.html), HTML Basics
(quarto.org/docs/output-formats/html-basics.html), Cross References
(quarto.org/docs/authoring/cross-references.html).

You write only the **body** of `/notes/index.qmd`. The server adds the title (the lecture topic),
the table of contents, numbering, citations and styling. Never write a `---` metadata block.

## The page shape

1. **What you will learn**: a `callout-note` with 3 to 5 concrete objectives ("compute...",
   "explain why...", "recognise when..."). No section heading before it.
2. **Why it matters**: one short paragraph or a concrete motivating example (a hook), as the
   first `##` section.
3. **Concept sections**: one `##` per big idea from the syllabus subtopics, in teaching order.
   Inside each, `###` for sub-steps. Each section follows: intuition, then the formal statement,
   then a worked example, then a check-yourself question. Put a visual in most sections.
4. **Putting it together**: how the ideas connect, ideally a concept map (`{dot}`).
5. **Summary**: a `callout-important` with the 5 to 8 points a student must remember.
6. **Key terms**: a two-column table (term, meaning), with the original-language term in
   brackets when the reading is in another language.

Keep sections short. One idea per section beats one long section with many ideas. Aim for a page
a student can read in 20 to 40 minutes.

## Headings and ids

```markdown
## Eigenvalues as stretch factors {#sec-stretch}

### Finding them {#sec-finding}
```

- Give every `##` an id starting with `sec-`, lowercase, words joined by `-`.
- Do not start the body with `#` (level 1); the title is already there.
- Refer to a section with `@sec-stretch`. Quarto writes "Section 2" (or the localised word).

## Cross-references

| What | Label | Reference |
|------|-------|-----------|
| Section | `## Title {#sec-name}` | `@sec-name` |
| Figure (diagram or SVG) | `//| label: fig-name` or `![Cap](assets/x.svg){#fig-name}` | `@fig-name` |
| Table | caption line `: Caption {#tbl-name}` under the table | `@tbl-name` |
| Equation | `$$ ... $$ {#eq-name}` | `@eq-name` |
| Definition / theorem | `::: {#def-name}` / `::: {#thm-name}` | `@def-name` |

Every label you reference must exist; `render_notes` reports unresolved ones.

## Text

- `**bold**` for the first use of a key term, `*italic*` for emphasis. Do not overuse either.
- Footnotes `^[like this]` for asides that would break the flow; they show in the margin.
- Lists for steps and enumerations, prose for explanations. A list of fragments does not explain.
- Horizontal rules: `***` (never `---`).
- Links only to `https://` pages that a reading cites; never invent URLs.
