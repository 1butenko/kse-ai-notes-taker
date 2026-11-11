---
name: worked-examples-and-self-check
description: Use in every concept section. Worked examples with every step shown, faded examples, "try it" exercises with collapsed solutions, misconception warnings and short retrieval questions that make students think instead of just read.
---

# Worked examples and self-checks

Quarto docs: Callouts, collapse (quarto.org/docs/authoring/callouts.html#collapse), Theorems and
examples (quarto.org/docs/authoring/cross-references-divs.html).

Students learn from examples more than from definitions. Every concept section gets at least one.

## Worked example

```markdown
::: {#exm-2x2}
## Eigenvalues of a 2×2 matrix
Find the eigenvalues of $A = \begin{pmatrix} 2 & 1 \\ 1 & 2 \end{pmatrix}$.

**Step 1. Set up.** We need $\det(A - \lambda I) = 0$ (@eq-char).

**Step 2. Expand.** $(2-\lambda)^2 - 1 = 0$.

**Step 3. Solve.** $\lambda = 1$ or $\lambda = 3$.

**Check.** The trace is $4 = 1 + 3$ and the determinant is $3 = 1 \cdot 3$. ✓
:::
```

- Name each step and say *why* it is the next move, not only what it is.
- End with a check (substitute back, a sanity check, units, a special case).
- Use the reading's own examples first, with their page cited. Add your own only to fill a gap,
  and mark it "(our example)".

## Faded example, then try it

After a full worked example, give a similar one with the last steps left to the student:

```markdown
::: {.callout-tip title="Try it"}
Find the eigenvalues of $B = \begin{pmatrix} 4 & 1 \\ 2 & 3 \end{pmatrix}$.
:::

::: {.callout-note collapse="true" title="Solution"}
$\det(B - \lambda I) = \lambda^2 - 7\lambda + 10 = (\lambda - 2)(\lambda - 5)$, so
$\lambda \in \{2, 5\}$.
:::
```

Always give the full solution, collapsed. Solutions you are not sure of do not belong in notes.

## Misconceptions

When the reading warns about a mistake, or one is common, show it:

```markdown
::: {.callout-warning title="Common mistake"}
An eigenvector cannot be $0$, even though $A0 = \lambda 0$ for every $\lambda$.
:::
```

## Retrieval questions

End each section, or the page, with 2 to 4 short questions that require recalling or applying
the idea, not copying a sentence. Put answers in one collapsed callout.

```markdown
::: {.callout-note title="Check yourself"}
1. Why can't an eigenvector be zero?
2. What are the eigenvalues of a triangular matrix?
:::

::: {.callout-note collapse="true" title="Answers"}
1. ...
2. The entries on its diagonal.
:::
```

An interactive self-check (ojs-interactive) is a good alternative for one key question.
