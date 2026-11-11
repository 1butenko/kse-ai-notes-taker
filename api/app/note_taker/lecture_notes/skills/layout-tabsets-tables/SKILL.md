---
name: layout-tabsets-tables
description: Use to organise a page visually - tabsets (Intuition / Formal / Example, or method A vs B), side-by-side columns, margin asides, figure grids, and captioned comparison tables.
---

# Layout, tabsets and tables

Quarto docs: Tabsets (quarto.org/docs/output-formats/html-basics.html#tabsets), Article Layout
(quarto.org/docs/authoring/article-layout.html), Figure layout
(quarto.org/docs/authoring/figures.html#complex-layouts), Tables
(quarto.org/docs/authoring/tables.html).

## Tabsets: the same idea, several views

```markdown
::: {.panel-tabset group="views"}
## Intuition
A matrix moves most vectors off their line; eigenvectors stay on it.

## Formal
$Av = \lambda v$, $v \ne 0$.

## Example
For $A = \begin{pmatrix} 2 & 0 \\ 0 & 3 \end{pmatrix}$, $e_1$ and $e_2$ are eigenvectors.
:::
```

- Each `##` inside the div is one tab; these headings get no number and no TOC entry.
- `group="..."` keeps tabs with the same names in sync across the page.
- Good uses: intuition/formal/example; two methods side by side; one example per case.
- Bad use: hiding the main explanation. The first tab must stand on its own.

## Columns

```markdown
:::: {.columns}
::: {.column width="50%"}
Text explaining the picture.
:::
::: {.column width="50%"}
![Caption](assets/picture.svg){#fig-picture}
:::
::::
```

The outer div needs more colons than the inner ones.

## Margin

```markdown
::: {.column-margin}
**Historical note.** Cauchy introduced the term in 1829.
:::
```

Use the margin for asides, small figures, definitions recalled from earlier lectures. Wider
figures: `.column-page` or `.column-body-outset` around the figure.

## Figure grids

```markdown
::: {layout-ncol=2}
![Before](assets/before.svg){#fig-before}

![After](assets/after.svg){#fig-after}
:::
```

## Tables

```markdown
| Method | When it works | Cost |
|--------|---------------|------|
| Characteristic polynomial | Small matrices | $O(n^3)$ and up |
| Power iteration | Dominant eigenvalue only | $O(n^2)$ per step |

: Methods for finding eigenvalues {#tbl-methods tbl-colwidths="[30,45,25]"}
```

- Comparison tables are one of the clearest visuals: use them for "X vs Y", properties of cases,
  and key terms.
- Keep cells short; math is fine. Every table has a caption line with a `tbl-` id.
