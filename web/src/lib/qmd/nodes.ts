/** Editor nodes for the Quarto constructs Markdown has no node for. Plain Markdown (paragraphs,
 * headings, lists, tables, code, quotes, math) uses Plate's own nodes. */

import type { Attrs } from "./attrs"

export const QDIV = "qdiv" // ::: {.callout-note} ... :::, theorems, columns, margin, ...
export const QTAB = "qtab" // one tab of a .panel-tabset div (its heading and content)
export const QCELL = "qcell" // ```{dot} / {mermaid} / {ojs} cells
export const QFIGURE = "qfigure" // ![Caption](assets/x.svg){#fig-x}
export const QCAPTION = "qcaption" // `: Caption {#tbl-x}` under a table
export const QDETAILS = "qdetails" // <details><summary>...</summary> ... </details>
export const QRAW = "qraw" // anything kept verbatim
export const QINLINE = "qinline" // [@r1, p. 3], @sec-x, [text]{.mark}
export const EQUATION = "equation" // Plate's display math; `label` holds its #eq- id
export const HEADING_ATTRS = "attrs" // on h1..h6: {#sec-x .unnumbered}

export type CellKind = "dot" | "mermaid" | "ojs"
export const CELL_KINDS: CellKind[] = ["dot", "mermaid", "ojs"]

export type InlineKind = "cite" | "xref" | "span" | "raw"

type Empty = [{ text: "" }]
type Block = { type: string; children: unknown[]; [key: string]: unknown }

export type QDivElement = { type: typeof QDIV; attrs: Attrs; children: Block[] }
export type QTabElement = { type: typeof QTAB; title: string; level: number; children: Block[] }
export type QCellElement = {
  type: typeof QCELL
  kind: CellKind
  /** The `#|` / `//|` / `%%|` option lines, as written. */
  options: string[]
  code: string
  children: Empty
}
export type QFigureElement = {
  type: typeof QFIGURE
  src: string
  caption: string
  attrs: Attrs
  children: Empty
}
export type QCaptionElement = { type: typeof QCAPTION; text: string; children: Empty }
export type QDetailsElement = { type: typeof QDETAILS; summary: string; children: Block[] }
export type QRawElement = { type: typeof QRAW; source: string; children: Empty }
export type QInlineElement = {
  type: typeof QINLINE
  kind: InlineKind
  source: string
  children: Empty
}

export const empty = (): Empty => [{ text: "" }]

/** Cross-reference ids Quarto numbers; anything else after `@` is a citation key. */
export const XREF_PREFIXES = [
  "sec-",
  "fig-",
  "tbl-",
  "eq-",
  "thm-",
  "lem-",
  "cor-",
  "prp-",
  "def-",
  "exm-",
  "exr-",
  "cnj-",
  "rem-",
]

export const THEOREM_KINDS: Record<string, string> = {
  "thm-": "Theorem",
  "lem-": "Lemma",
  "cor-": "Corollary",
  "prp-": "Proposition",
  "def-": "Definition",
  "exm-": "Example",
  "exr-": "Exercise",
  "cnj-": "Conjecture",
  "rem-": "Remark",
}
