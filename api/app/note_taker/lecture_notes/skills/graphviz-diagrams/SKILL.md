---
name: graphviz-diagrams
description: Use for concept maps, hierarchies, decision trees, causal graphs, state machines and any node-and-arrow picture. Graphviz {dot} cells are drawn at render time, so their errors come back to you; prefer them over Mermaid for important diagrams.
---

# Graphviz diagrams

Quarto docs: Diagrams (quarto.org/docs/authoring/diagrams.html). Graphviz reference:
graphviz.org/doc/info/lang.html, graphviz.org/doc/info/attrs.html.

`{dot}` cells are turned into inline SVG while `render_notes` runs. A syntax error makes the
render fail with Graphviz's message, so you can fix it.

## Template

````markdown
```{dot}
//| label: fig-concepts
//| fig-cap: "How the main ideas connect"
digraph G {
  rankdir=LR;
  bgcolor="transparent";
  node [shape=box, style="rounded,filled", fillcolor="#eef4fb", color="#4a78b5",
        fontname="Helvetica", fontsize=12];
  edge [color="#666666", fontname="Helvetica", fontsize=10];

  matrix  [label="Матриця A"];
  eigen   [label="Власні значення λ"];
  vectors [label="Власні вектори v"];

  matrix -> eigen   [label="det(A − λI) = 0"];
  eigen  -> vectors [label="(A − λI)v = 0"];
}
```
````

- Cell options allowed: `label` (must start with `fig-`), `fig-cap`, `fig-alt`, `fig-width`,
  `fig-height`, `fig-align`. Start each with `//|`.
- Quote every label that has spaces, Cyrillic or symbols.
- `rankdir=LR` suits processes; `TB` suits hierarchies.
- Group related nodes with `subgraph cluster_x { label="..."; style="rounded,dashed"; ... }`.
- Use at most 3 fill colours with meaning, and say in the caption what they mean.
- Keep it to roughly 15 nodes. Split a bigger picture into two figures.
- Not allowed: `image=`, `imagepath=`, `shapefile=`, `fontpath=`. Diagrams cannot load files.

## Diagram ideas for lectures

| Situation | Diagram |
|-----------|---------|
| The lecture's ideas and how they depend on each other | Concept map (`digraph`, `LR`) |
| Classification or taxonomy | Tree (`TB`, `shape=box`) |
| An algorithm with branches | Flowchart (`shape=diamond` for decisions) |
| States and transitions (automata, Markov chains, life cycles) | `circle` nodes, labelled edges |
| Cause and effect | `LR` graph, edge labels for the mechanism |
| Proof structure: which lemma gives which result | `TB` graph from axioms to theorem |

Reference every diagram in the text ("@fig-concepts shows..."). Say what to look at; a diagram
nobody explains is decoration.
