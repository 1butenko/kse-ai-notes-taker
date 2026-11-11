---
name: callouts-and-theorems
description: Use when marking definitions, theorems, proofs, warnings, tips or summaries. Which callout type means what, collapsed derivations, and numbered definition/theorem/example blocks that can be cross-referenced.
---

# Callouts and theorem blocks

Quarto docs: Callout Blocks (quarto.org/docs/authoring/callouts.html), Theorems and Proofs
(quarto.org/docs/authoring/cross-references-divs.html).

## Callouts: one meaning each

| Type | Use it for |
|------|-----------|
| `callout-note` | Objectives, context, "in other words" restatements |
| `callout-tip` | Intuition, memory aids, shortcuts, a worked example's key move |
| `callout-important` | The summary, a result students must remember |
| `callout-warning` | Common mistakes and misconceptions |
| `callout-caution` | Conditions that must hold (a theorem fails without them) |

```markdown
::: {.callout-warning title="Common mistake"}
$\det(A + B) \ne \det A + \det B$ in general. Check with $A = B = I_2$.
:::
```

- Always give a short `title`. Keep callouts short (1 to 6 lines); they lose force when long.
- At most one callout in a row; never nest callouts.
- Collapse long material a student may skip on first read:

```markdown
::: {.callout-note collapse="true" title="Full derivation"}
The step-by-step working goes here.
:::
```

- `appearance="simple"` gives a lighter box; `icon=false` hides the icon. Use sparingly.

## Definitions, theorems, examples

Numbered blocks use a div with an id prefix. The first heading inside is its name:

```markdown
::: {#def-eigen}
## Eigenvector
A non-zero vector $v$ is an **eigenvector** of $A$ if $Av = \lambda v$ for some scalar $\lambda$.
:::

::: {#thm-char}
## Characteristic equation
$\lambda$ is an eigenvalue of $A$ exactly when $\det(A - \lambda I) = 0$.
:::

As @thm-char shows, ...
```

Prefixes: `def-` definition, `thm-` theorem, `lem-` lemma, `cor-` corollary, `prp-` proposition,
`exm-` example, `exr-` exercise, `rem-` remark, `cnj-` conjecture.

Proofs: put them in a collapsed `callout-note` titled "Proof" right after the theorem, so the
statement stays visible and the proof is one click away.

Rules:
- State a definition exactly as precisely as the reading does; then explain it in plain words
  after the block, never inside it.
- Every theorem gets its conditions spelled out. If the reading proves it, sketch the proof idea
  in one or two sentences outside the collapsed full proof.
