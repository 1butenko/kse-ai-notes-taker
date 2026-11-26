/** The ids a note defines (#sec-, #fig-, #thm-, ...) for cross-references, and renaming one
 * together with every `@id` that points at it. */

import { parseAttrs } from "./attrs"
import {
  EQUATION,
  HEADING_ATTRS,
  QCAPTION,
  QCELL,
  QDIV,
  QFIGURE,
  QINLINE,
  THEOREM_KINDS,
  XREF_PREFIXES,
} from "./nodes"

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- Plate nodes are open records.
type Node = Record<string, any>

export type DefinedId = {
  id: string
  /** What it is: Section, Figure, Theorem, ... */
  kind: string
  /** Its text: a heading, caption, name or TeX. */
  text: string
}

export const ID_KINDS: Record<string, string> = {
  "sec-": "Section",
  "fig-": "Figure",
  "tbl-": "Table",
  "eq-": "Equation",
  ...THEOREM_KINDS,
}

export const kindOfId = (id: string) =>
  ID_KINDS[XREF_PREFIXES.find((p) => id.startsWith(p)) ?? ""] ?? "Reference"

const textOf = (node: Node): string =>
  typeof node.text === "string"
    ? node.text
    : node.type === QINLINE
      ? node.source
      : node.type === "inline_equation"
        ? `$${node.texExpression}$`
        : Array.isArray(node.children)
          ? node.children.map(textOf).join("")
          : ""

const cellLabel = (options: string[]) =>
  options.map((o) => o.match(/\|\s*label:\s*["']?([\w-]+)/)?.[1]).find(Boolean)
const cellCaption = (options: string[]) =>
  options.map((o) => o.match(/\|\s*fig-cap:\s*["']?(.*?)["']?\s*$/)?.[1]).find(Boolean)

/** Every id the note defines, in document order. */
export function definedIds(nodes: Node[]): DefinedId[] {
  const out: DefinedId[] = []
  const add = (id: string | undefined, text: string) => {
    if (id && XREF_PREFIXES.some((p) => id.startsWith(p))) {
      out.push({ id, kind: kindOfId(id), text: text.trim() })
    }
  }
  const walk = (node: Node) => {
    if (/^h[1-6]$/.test(node.type)) add(node[HEADING_ATTRS]?.id, textOf(node))
    else if (node.type === QDIV) {
      const first = node.children?.[0]
      add(node.attrs?.id, first && /^h[1-6]$/.test(first.type) ? textOf(first) : "")
    } else if (node.type === QFIGURE) add(node.attrs?.id, node.caption)
    else if (node.type === EQUATION) add(node.label, node.texExpression)
    else if (node.type === QCELL) add(cellLabel(node.options), cellCaption(node.options) ?? "")
    else if (node.type === QCAPTION) {
      const attrs = node.text.match(/\{([^{}]*)\}\s*$/)
      add(attrs ? parseAttrs(attrs[0])?.id : undefined, node.text.replace(/\{[^{}]*\}\s*$/, ""))
    }
    if (Array.isArray(node.children)) node.children.forEach(walk)
  }
  nodes.forEach(walk)
  return out
}

/** A cross-reference `@old` (or `-@old`) in a citation-like source, renamed. */
function renameIn(source: string, from: string, to: string): string {
  return source.replace(
    new RegExp(`(^|[^\\w@])(-?@)${from.replace(/[.*+?^${}()|[\]\\-]/g, "\\$&")}(?![\\w:-])`, "g"),
    `$1$2${to}`,
  )
}

/** The paths and new `source`s of every cross-reference to `from`, to point them at `to`. */
export function referencesTo(nodes: Node[], from: string, to: string): [number[], string][] {
  const out: [number[], string][] = []
  const walk = (node: Node, path: number[]) => {
    if (node.type === QINLINE && node.kind !== "raw") {
      const renamed = renameIn(node.source, from, to)
      if (renamed !== node.source) out.push([path, renamed])
    }
    if (Array.isArray(node.children)) node.children.forEach((c: Node, i: number) => walk(c, [...path, i]))
  }
  nodes.forEach((n, i) => walk(n, [i]))
  return out
}

/** Whether `id` is a usable new id with one of `prefixes`, not taken by another block. */
export function idProblem(id: string, prefixes: string[], taken: string[]): string | null {
  if (!prefixes.some((p) => id.startsWith(p))) return `Start it with ${prefixes.join(", ")}`
  if (!/^[\w-]+$/.test(id) || prefixes.includes(id)) return "Letters, digits and dashes after the prefix"
  if (taken.includes(id)) return "Another block already has this id"
  return null
}
