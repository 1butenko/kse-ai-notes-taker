---
name: math-explanations
description: Use whenever the lecture has formulas. How to write MathJax-safe math in Quarto, number equations, and explain derivations step by step so every symbol and every step is justified.
---

# Explaining math

Quarto docs: Equations (quarto.org/docs/authoring/markdown-basics.html#equations), Cross
references to equations (quarto.org/docs/authoring/cross-references.html#equations).

Math is rendered by MathJax in the reader's browser.

## Syntax

- Inline: `$a^2 + b^2 = c^2$`. No space after the opening `$` or before the closing `$`.
- Display, numbered:

```markdown
$$
\det(A - \lambda I) = 0
$$ {#eq-char}
```

- Multi-line derivations use `aligned` inside one display block:

```markdown
$$
\begin{aligned}
\det\begin{pmatrix} 2-\lambda & 1 \\ 1 & 2-\lambda \end{pmatrix}
  &= (2-\lambda)^2 - 1 && \text{expand the } 2\times 2 \text{ determinant} \\
  &= (\lambda - 1)(\lambda - 3) && \text{difference of squares}
\end{aligned}
$$
```

- Allowed: standard LaTeX math, `\text{}`, `\operatorname{}`, `\underbrace{}_{}`,
  `\overbrace{}^{}`, `\boxed{}`, `\color{}`, `pmatrix`/`bmatrix`/`cases`/`aligned`.
- Not allowed (rejected by `render_notes`): `\href`, `\url`, `\require`, `\input`, `\include`,
  `\class`, `\cssId`, `\style`, `\unicode`.
- Cyrillic inside math goes in `\text{...}`.
- A `$` meaning money is written `\$`.

## Explaining

1. **Say it in words first.** "We are looking for the directions that $A$ only stretches."
2. **Introduce every symbol** right after the formula that first uses it: a short "where"
   list, or a table for many symbols.
3. **One step per line** in derivations, each with its reason in the `&&` column.
4. **Annotate** the key parts with `\underbrace{...}_{\text{meaning}}`.
5. **Check with numbers.** After a general result, plug in a small concrete case.
6. **Link the formula to the picture.** If a diagram or an interactive widget shows the same
   idea, reference it: "see @fig-stretch".

Copy formulas from the reading exactly. Fix only clear transcription errors (a missing bracket
in the PDF text), and only when the page shows what it must be.
