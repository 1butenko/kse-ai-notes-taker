---
name: ojs-interactive
description: Use when a concept changes with a parameter (a slider shows the effect), when a function, distribution or process is easier to explore than to read about, or for a small interactive self-check. Observable JS {ojs} cells with Inputs and Plot, running in the reader's browser with inline data only.
---

# Interactive explorers with Observable JS

Quarto docs: Observable JS (quarto.org/docs/interactive/ojs/), OJS Libraries
(quarto.org/docs/interactive/ojs/libraries.html), Code Cells
(quarto.org/docs/interactive/ojs/ojs-cells.html), Layout
(quarto.org/docs/interactive/layout.html).

`{ojs}` cells run in the student's browser. They are reactive: when an input changes, every cell
that uses it re-runs. `Inputs`, `Plot` and `d3` are available without importing.

## Template: a slider that changes a plot

````markdown
```{ojs}
//| echo: false
viewof k = Inputs.range([0.2, 3], {value: 1, step: 0.1, label: "Stretch factor λ"})
```

```{ojs}
//| echo: false
//| label: fig-stretch
//| fig-cap: "The vector v and Av = λv for the chosen λ"
Plot.plot({
  aspectRatio: 1,
  x: {domain: [-3, 3]}, y: {domain: [-3, 3]},
  marks: [
    Plot.ruleX([0]), Plot.ruleY([0]),
    Plot.arrow([{x1: 0, y1: 0, x2: 1, y2: 0.5}], {x1: "x1", y1: "y1", x2: "x2", y2: "y2", stroke: "gray"}),
    Plot.arrow([{x1: 0, y1: 0, x2: k, y2: 0.5 * k}], {x1: "x1", y1: "y1", x2: "x2", y2: "y2", stroke: "steelblue", strokeWidth: 2})
  ]
})
```
````

## Patterns that teach

| Idea | Widget |
|------|--------|
| A parameter's effect on a curve | `Inputs.range` + `Plot.line` of computed points |
| Sampling, randomness, convergence | A sample-size slider + histogram (`Plot.rectY` with `Plot.binX`) |
| Comparing cases | `Inputs.radio` or `Inputs.select` choosing which case to plot |
| Step-by-step algorithm | `Inputs.range` over the step number, show the state at that step |
| Quick self-check | `Inputs.radio` with options, then a cell showing "Correct" or a hint |

Compute data inline: `d3.range(-5, 5, 0.05).map(x => ({x, y: Math.sin(k * x)}))`.

## Rules (enforced by render_notes)

- At most 6 `{ojs}` cells per note. One or two good explorers beat many small ones.
- Always `//| echo: false`: students see the widget, not the code.
- Inline data only. Not allowed: `FileAttachment`, `fetch`, `import`, `require`, URLs, storage,
  `window.parent`/`top`/`opener`, `postMessage`, `eval`, `Function`.
- Allowed cell options: `echo`, `label` (`fig-`), `fig-cap`, `fig-alt`, `panel`
  (`input`, `sidebar`, `fill`, `center`), `code-fold`.
- Put the explanation in prose next to the widget: what to try ("move λ below 1") and what to
  notice ("the vector shrinks but keeps its direction").
- Make sure the page still makes sense without JavaScript: the text must not depend on the
  widget to state a result.

## Layout

A sidebar of inputs next to the output:

````markdown
::: {.panel-sidebar}
```{ojs}
//| echo: false
viewof n = Inputs.range([10, 1000], {step: 10, value: 100, label: "Sample size"})
```
:::

::: {.panel-fill}
```{ojs}
//| echo: false
Plot.rectY(d3.range(n).map(() => d3.randomNormal()()), Plot.binX({y: "count"})).plot()
```
:::
````
