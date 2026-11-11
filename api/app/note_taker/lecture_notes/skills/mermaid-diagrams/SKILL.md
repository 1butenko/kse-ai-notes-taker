---
name: mermaid-diagrams
description: Use for sequence diagrams, timelines and simple flowcharts where Mermaid's layout reads better than Graphviz. Mermaid draws in the reader's browser, so syntax errors are never reported to you - keep to the safe subset here and keep diagrams small.
---

# Mermaid diagrams

Quarto docs: Diagrams (quarto.org/docs/authoring/diagrams.html). Mermaid syntax:
mermaid.js.org/intro/syntax-reference.html.

**Warning:** `render_notes` cannot check Mermaid. A broken diagram shows as an error box only in
the student's browser. For any diagram the lecture depends on, use `{dot}` (graphviz-diagrams).
Use Mermaid when its diagram type has no good Graphviz equivalent: sequence diagrams and
timelines.

## Safe subset

````markdown
```{mermaid}
%%| label: fig-handshake
%%| fig-cap: "TCP three-way handshake"
sequenceDiagram
  participant C as "Client"
  participant S as "Server"
  C->>S: SYN
  S->>C: SYN-ACK
  C->>S: ACK
```
````

````markdown
```{mermaid}
%%| label: fig-history
%%| fig-cap: "Milestones"
timeline
  title Розвиток теорії
  1900 : Перша ідея
  1950 : Доведення
  2000 : Застосування
```
````

````markdown
```{mermaid}
%%| label: fig-flow
%%| fig-cap: "Choosing a method"
flowchart LR
  A["Square matrix?"] -->|yes| B["Compute det(A − λI)"]
  A -->|no| C["Use singular values"]
```
````

Rules that avoid most errors:
- Cell options start with `%%|` (not `//|`).
- Put every node label in double quotes: `A["Текст (з дужками)"]`.
- Node ids are plain ASCII letters and digits: `A`, `step2`.
- No semicolons at line ends, no HTML in labels, no `click` lines, no `%%{init}` directives
  (both are rejected).
- At most about 10 nodes or 8 messages per diagram.
- Allowed types: `flowchart`, `sequenceDiagram`, `timeline`, `stateDiagram-v2`, `classDiagram`,
  `pie`, `mindmap`. Prefer the first three.

Re-read every Mermaid block character by character before rendering. The reviewer checks them
too.
