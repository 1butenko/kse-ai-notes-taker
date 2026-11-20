/** A lecture note's Quarto body (index.qmd without front matter) to editor nodes and back.
 *
 * Two layers:
 * - a block scanner for what only Pandoc has: fenced divs, executable cells, labelled display
 *   math, figures, table captions, <details>;
 * - Plate's Markdown converter (remark) for the Markdown between them. Pandoc's inline syntax
 *   (citations, cross-references, `[x]{.mark}` spans, heading attributes) is swapped for plain
 *   tokens first, so remark neither parses nor escapes it, and swapped back after.
 *
 * Whatever the scanner can't place is kept verbatim in a `qraw` node, so saving never loses
 * text. `serializeQmd(parseQmd(x))` is stable: parsing it again gives the same nodes.
 */

import { deserializeMd, serializeMd } from "@platejs/markdown"
import type { SlateEditor } from "platejs"

import { type Attrs, emptyAttrs, formatAttrs, hasAttrs, parseAttrs } from "./attrs"
import {
  type CellKind,
  CELL_KINDS,
  empty,
  EQUATION,
  HEADING_ATTRS,
  type InlineKind,
  QCAPTION,
  QCELL,
  QDETAILS,
  QDIV,
  QFIGURE,
  QINLINE,
  QRAW,
  QTAB,
  XREF_PREFIXES,
} from "./nodes"

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- Plate nodes are open records.
type Node = Record<string, any>

const CUSTOM = new Set([QDIV, QTAB, QCELL, QFIGURE, QCAPTION, QDETAILS, QRAW, EQUATION])
const HEADINGS = new Set(["h1", "h2", "h3", "h4", "h5", "h6"])
const INLINE_EQUATION = "inline_equation"
const OPTION = /^\s*(?:#\||\/\/\||%%\|)/
// Tokens are bracketed in Unicode punctuation: remark never escapes it, and emphasis next to a
// token (`@eq-m**.**`) reads as it would next to the citation Pandoc sees.
const TOKEN = /⟦(\d+)⟧/g
const token = (n: number) => `⟦${n}⟧`

// Parsing

type Segment = Node | { md: string[] }

export function parseQmd(editor: SlateEditor, body: string): Node[] {
  const nodes = blocksToNodes(editor, scan(body.replace(/\r\n?/g, "\n").split("\n")))
  return nodes.length ? nodes : [{ type: "p", children: [{ text: "" }] }]
}

const isBlank = (line: string | undefined) => line === undefined || line.trim() === ""

function fenceEnd(lines: string[], start: number, fence: string): number {
  for (let j = start + 1; j < lines.length; j++) {
    const m = lines[j].match(/^\s*(`{3,}|~{3,})\s*$/)
    if (m && m[1][0] === fence[0] && m[1].length >= fence.length) return j
  }
  return -1
}

const DIV_OPEN = /^(:{3,})\s*(\S.*?)\s*:*\s*$/
const DIV_CLOSE = /^:{3,}\s*$/

function divEnd(lines: string[], start: number): number {
  let depth = 1
  for (let j = start + 1; j < lines.length; j++) {
    const fence = lines[j].match(/^\s*(`{3,}|~{3,})/)
    if (fence) {
      const end = fenceEnd(lines, j, fence[1])
      if (end < 0) return -1
      j = end
      continue
    }
    if (DIV_CLOSE.test(lines[j])) {
      if (--depth === 0) return j
    } else if (DIV_OPEN.test(lines[j])) depth++
  }
  return -1
}

/** Split lines into Pandoc-only blocks and the Markdown between them. */
function scan(lines: string[]): Segment[] {
  const out: Segment[] = []
  let md: string[] = []
  const flush = () => {
    if (md.some((l) => l.trim())) out.push({ md })
    md = []
  }
  const raw = (from: number, to: number) => {
    flush()
    out.push({ type: QRAW, source: lines.slice(from, to + 1).join("\n"), children: empty() })
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]

    const fence = line.match(/^(\s*)(`{3,}|~{3,})\s*(.*?)\s*$/)
    if (fence) {
      const end = fenceEnd(lines, i, fence[2])
      if (end < 0) {
        raw(i, lines.length - 1)
        break
      }
      const cell = fence[3].match(/^\{\s*([\w-]+)\s*\}$/)
      if (cell && !fence[1] && CELL_KINDS.includes(cell[1] as CellKind)) {
        flush()
        const inner = lines.slice(i + 1, end)
        let n = 0
        while (n < inner.length && OPTION.test(inner[n])) n++
        out.push({
          type: QCELL,
          kind: cell[1],
          options: inner.slice(0, n),
          code: inner.slice(n).join("\n"),
          children: empty(),
        })
      } else md.push(...lines.slice(i, end + 1))
      i = end
      continue
    }

    const div = line.match(DIV_OPEN)
    if (div) {
      const end = divEnd(lines, i)
      const attrs = parseAttrs(div[2])
      if (end < 0 || !attrs) {
        raw(i, end < 0 ? lines.length - 1 : end)
        if (end < 0) break
        i = end
        continue
      }
      flush()
      out.push(divNode(attrs, scan(lines.slice(i + 1, end))))
      i = end
      continue
    }

    if (/^\s+:{3,}/.test(line)) {
      // A div inside a list item: keep the whole Markdown block as written.
      let end = i
      while (end + 1 < lines.length && !isBlank(lines[end + 1])) end++
      let start = md.length
      while (start > 0 && !isBlank(md[start - 1])) start--
      const before = md.splice(start)
      flush()
      out.push({
        type: QRAW,
        source: [...before, ...lines.slice(i, end + 1)].join("\n"),
        children: empty(),
      })
      i = end
      continue
    }

    if (/^\s*\$\$/.test(line)) {
      const math = displayMath(lines, i)
      if (math) {
        flush()
        out.push(math.node)
        i = math.end
        continue
      }
    }

    const figure = line.match(/^!\[(.*)\]\((assets\/[^)\s]+)\)(\{[^{}]*\})?\s*$/)
    if (figure && isBlank(md.at(-1)) && isBlank(lines[i + 1])) {
      const attrs = figure[3] ? parseAttrs(figure[3]) : emptyAttrs()
      if (attrs) {
        flush()
        out.push({
          type: QFIGURE,
          src: figure[2],
          caption: figure[1],
          attrs,
          children: empty(),
        })
        continue
      }
    }

    const caption = line.match(/^:\s+(.*\S)\s*$/)
    if (caption && lastContent(md)?.trimStart().startsWith("|")) {
      flush()
      out.push({ type: QCAPTION, text: caption[1], children: empty() })
      continue
    }

    if (/^<details>\s*$/i.test(line)) {
      const end = lines.findIndex((l, j) => j > i && /^<\/details>\s*$/i.test(l))
      const summary = lines[i + 1]?.match(/^<summary>(.*)<\/summary>\s*$/i)
      if (end > 0 && summary) {
        flush()
        out.push({
          type: QDETAILS,
          summary: summary[1],
          children: scan(lines.slice(i + 2, end)),
        })
        i = end
        continue
      }
    }

    md.push(line)
  }
  flush()
  return out
}

const lastContent = (lines: string[]) => [...lines].reverse().find((l) => l.trim())

function displayMath(lines: string[], i: number): { node: Node; end: number } | null {
  const first = lines[i].trim().slice(2)
  // `$$ x $$ {#eq-a}` on one line, or `$$` ... `$$ {#eq-a}` over several.
  const single = first.match(/^(.*?)\$\$\s*(\{[^{}]*\})?\s*$/)
  if (single && single[1].trim()) return mathNode(single[1], single[2], i)
  const tex = [first]
  for (let j = i + 1; j < lines.length; j++) {
    const close = lines[j].match(/^(.*?)\$\$\s*(\{[^{}]*\})?\s*$/)
    if (close) return mathNode([...tex, close[1]].join("\n"), close[2], j)
    if (isBlank(lines[j])) return null
    tex.push(lines[j])
  }
  return null
}

function mathNode(tex: string, label: string | undefined, end: number) {
  const attrs = label ? parseAttrs(label) : null
  if (label && !attrs) return null
  return {
    node: {
      type: EQUATION,
      texExpression: tex.trim(),
      // Not `id`: Plate gives every block one of its own.
      ...(attrs?.id ? { label: attrs.id } : {}),
      children: empty(),
    },
    end,
  }
}

function divNode(attrs: Attrs, children: Segment[]): Node {
  if (attrs.classes.includes("panel-tabset")) {
    const tabs = tabsOf(children)
    if (tabs) return { type: QDIV, attrs, children: tabs }
  }
  return { type: QDIV, attrs, children }
}

/** A tabset's segments as tabs: each heading of its top level starts one. Null when there is
 * content before the first heading. */
function tabsOf(segments: Segment[]): Node[] | null {
  // Headings sit in the Markdown segments; split those at the shallowest heading level.
  const flat: (Segment | { heading: string; level: number })[] = []
  for (const segment of segments) {
    if (!("md" in segment)) {
      flat.push(segment)
      continue
    }
    let current: string[] = []
    for (const line of segment.md) {
      const h = line.match(/^(#{1,6})\s+(.*?)\s*$/)
      if (h) {
        if (current.some((l) => l.trim())) flat.push({ md: current })
        current = []
        flat.push({ heading: h[2], level: h[1].length })
      } else current.push(line)
    }
    if (current.some((l) => l.trim())) flat.push({ md: current })
  }
  const levels = flat.filter((s) => "heading" in s).map((s) => (s as { level: number }).level)
  if (!levels.length || !("heading" in flat[0])) return null
  const level = Math.min(...levels)
  const tabs: Node[] = []
  for (const segment of flat) {
    if ("heading" in segment && segment.level === level) {
      tabs.push({ type: QTAB, title: segment.heading, level, children: [] })
    } else if ("heading" in segment) {
      const last = tabs.at(-1)!.children as Segment[]
      const md = "#".repeat(segment.level) + " " + segment.heading
      const prev = last.at(-1)
      if (prev && "md" in prev) prev.md.push("", md, "")
      else last.push({ md: [md, ""] })
    } else (tabs.at(-1)!.children as Segment[]).push(segment)
  }
  return tabs
}

/** Turn segments into nodes: Markdown through Plate, custom nodes recursively. */
function blocksToNodes(editor: SlateEditor, segments: Segment[]): Node[] {
  const out: Node[] = []
  for (const segment of segments) {
    if ("md" in segment) out.push(...markdownToNodes(editor, segment.md.join("\n")))
    else if (segment.type === QDIV || segment.type === QTAB || segment.type === QDETAILS) {
      const children = blocksToNodes(editor, segment.children as Segment[])
      out.push({
        ...segment,
        children: children.length ? children : [{ type: "p", children: [{ text: "" }] }],
      })
    } else out.push(segment)
  }
  return out
}

type Masked = { kind: InlineKind | "heading" | "math"; source: string }

const XREF = new RegExp(`^-?@(?:${XREF_PREFIXES.join("|")})`)

/** Replace Pandoc's inline syntax in Markdown with tokens; returns what each token stands for. */
export function maskInline(md: string): { md: string; masked: Masked[] } {
  const masked: Masked[] = []
  const put = (kind: Masked["kind"], source: string) => token(masked.push({ kind, source }) - 1)
  const out: string[] = []
  let fence: string | null = null
  for (const line of md.split("\n")) {
    const f = line.match(/^\s*(`{3,}|~{3,})/)
    if (fence) {
      if (f && f[1][0] === fence[0] && f[1].length >= fence.length) fence = null
      out.push(line)
      continue
    }
    if (f) {
      fence = f[1]
      out.push(line)
      continue
    }
    out.push(maskLine(line, put))
  }
  return { md: out.join("\n"), masked }
}

function maskLine(line: string, put: (kind: Masked["kind"], source: string) => string): string {
  // Code spans and math may hold @ and braces: set them aside first. Inline math becomes a token
  // too, so it keeps the bold or italic around it (Plate's reader drops marks on it).
  const kept: string[] = []
  const keep = (s: string) => `QMDK${kept.push(s) - 1}KQMD`
  // In a table row a | in math would end the cell for remark (Pandoc reads it as math): write
  // it as \vert (and \| as \Vert), which TeX draws the same.
  const row = /^\s*\|/.test(line)
  // A space after \vert only before a letter (\vert e, not \verte), never before the closing $.
  const bar = (command: string) => (_: string, next: string) =>
    command + (/[A-Za-z]/.test(next) ? " " : "") + next
  const math = (s: string) =>
    put(
      "math",
      row
        ? s.replace(/\\\|(.)/g, bar("\\Vert")).replace(/(?<!\\)\|(.)/g, bar("\\vert"))
        : s,
    )
  let text = line.replace(
    // Pandoc's inline math: no space inside the dollars, no digit after the closing one.
    /(`+)[^`]*?\1|\$\$.+?\$\$|(?<!\\)\$[^$\s](?:[^$\n]*?[^$\s\\])?\$(?!\d)/g,
    (s) => (s.startsWith("$") && !s.startsWith("$$") ? math(s) : keep(s)),
  )

  const heading = text.match(/^(#{1,6}\s.*?)\s+(\{[^{}]*\})\s*$/)
  if (heading && parseAttrs(heading[2])) text = `${heading[1]} ${put("heading", heading[2])}`

  text = text
    .replace(/!\[[^\]]*\]\([^)]*\)\{[^{}]*\}/g, (s) => put("raw", s))
    .replace(/\[([^[\]]*)\]\{([^{}]*)\}/g, (s, _t, attrs) =>
      parseAttrs(`{${attrs}}`) ? put("span", s) : s
    )
    .replace(/\[(?:[^[\]]*?[\s;])?-?@\w[^[\]]*\](?![({[])/g, (s) => put("cite", s))
    .replace(/(?<![\w@\\])-?@[A-Za-z0-9_](?:[\w:.-]*\w)?/g, (s) =>
      put(XREF.test(s) ? "xref" : "cite", s)
    )
  return text.replace(/QMDK(\d+)KQMD/g, (_, n) => kept[Number(n)])
}

function markdownToNodes(editor: SlateEditor, md: string): Node[] {
  const { md: plain, masked } = maskInline(md)
  const nodes = (deserializeMd(editor, plain, { withoutMdx: true }) as Node[]).map((node) =>
    unmask(node, masked),
  )
  // Plate's tables don't keep column alignment (|---:|): take it from the separator rows.
  const aligns = plain.split("\n").filter(isTableSeparator).map(alignOf)
  tablesIn(nodes).forEach((table, i) => {
    if (aligns[i]?.some(Boolean)) table.align = aligns[i]
  })
  return nodes
}

type Align = "left" | "right" | "center" | null

const isTableSeparator = (line: string) => line.includes("|") && /^[\s|:-]+$/.test(line) && line.includes("-")

function alignOf(separator: string): Align[] {
  return separator
    .trim()
    .replace(/^\||\|$/g, "")
    .split("|")
    .map((cell) => {
      const c = cell.trim()
      if (c.startsWith(":") && c.endsWith(":")) return "center"
      if (c.endsWith(":")) return "right"
      if (c.startsWith(":")) return "left"
      return null
    })
}

function tablesIn(nodes: Node[]): Node[] {
  return nodes.flatMap((n) =>
    n.type === "table" ? [n] : Array.isArray(n.children) ? tablesIn(n.children) : [],
  )
}

/** Write the tables' alignment back into the separator rows Plate wrote, in order. */
function withAlignment(md: string, nodes: Node[]): string {
  const tables = tablesIn(nodes)
  if (!tables.some((t) => t.align)) return md
  let i = 0
  return md
    .split("\n")
    .map((line) => {
      if (!isTableSeparator(line)) return line
      const align = tables[i++]?.align as Align[] | undefined
      if (!align) return line
      const cells = line.trim().replace(/^\||\|$/g, "").split("|")
      return (
        "|" +
        cells
          .map((cell, j) => {
            const dashes = "-".repeat(Math.max(3, cell.trim().length))
            const a = align[j]
            return " " + (a === "center" ? `:${dashes}:` : a === "right" ? `${dashes}:` : a === "left" ? `:${dashes}` : dashes) + " "
          })
          .join("|") +
        "|"
      )
    })
    .join("\n")
}

function unmask(node: Node, masked: Masked[]): Node {
  if (!Array.isArray(node.children)) return node
  let attrs: Attrs | undefined
  const children: Node[] = []
  for (const child of node.children as Node[]) {
    if (typeof child.text !== "string") {
      children.push(unmask(child, masked))
      continue
    }
    const { text, ...marks } = child
    let last = 0
    for (const m of (text as string).matchAll(TOKEN)) {
      const item = masked[Number(m[1])]
      const before = text.slice(last, m.index)
      last = m.index! + m[0].length
      if (item.kind === "heading") {
        attrs = parseAttrs(item.source) ?? undefined
        children.push({ ...marks, text: before.replace(/\s+$/, "") })
        continue
      }
      children.push({ ...marks, text: before })
      // The inline element keeps the marks of the text it sat in (`**from @tbl-x.**`).
      children.push(
        item.kind === "math"
          ? { ...marks, type: INLINE_EQUATION, texExpression: item.source.slice(1, -1), children: empty() }
          : { ...marks, type: QINLINE, kind: item.kind, source: item.source, children: empty() },
      )
    }
    children.push({ ...marks, text: text.slice(last) })
  }
  const merged = mergeTexts(children).filter(
    (c, i, all) => typeof c.text !== "string" || c.text !== "" || needsText(all, i)
  )
  return { ...node, children: merged, ...(attrs ? { [HEADING_ATTRS]: attrs } : {}) }
}

/** Adjacent text nodes with the same marks become one, as Slate would normalize them. */
function mergeTexts(children: Node[]): Node[] {
  const out: Node[] = []
  const marksOf = (node: Node) => JSON.stringify({ ...node, text: undefined })
  for (const child of children) {
    const prev = out.at(-1)
    if (
      prev &&
      typeof prev.text === "string" &&
      typeof child.text === "string" &&
      marksOf(prev) === marksOf(child)
    ) {
      out[out.length - 1] = { ...prev, text: prev.text + child.text }
    } else out.push(child)
  }
  return out
}

/** Slate wants a text node around every inline element. */
function needsText(children: Node[], i: number): boolean {
  const isInline = (n: Node | undefined) => n?.type === QINLINE || n?.type === "inline_equation"
  return (
    children.length === 1 ||
    isInline(children[i - 1]) ||
    isInline(children[i + 1]) ||
    (i === 0 && isInline(children[1]))
  )
}

// Serializing

export function serializeQmd(editor: SlateEditor, nodes: Node[]): string {
  return serializeBlocks(editor, nodes).replace(/\n{3,}/g, "\n\n").trim() + "\n"
}

function serializeBlocks(editor: SlateEditor, nodes: Node[]): string {
  const parts: string[] = []
  let run: Node[] = []
  const flush = () => {
    if (run.length) parts.push(markdownOf(editor, run))
    run = []
  }
  for (const node of nodes) {
    if (CUSTOM.has(node.type)) {
      flush()
      parts.push(serializeCustom(editor, node))
    } else run.push(node)
  }
  flush()
  return parts.filter((p) => p.trim()).join("\n\n")
}

function divDepth(node: Node): number {
  const children = Array.isArray(node.children) ? (node.children as Node[]) : []
  const inner = Math.max(0, ...children.map(divDepth))
  return node.type === QDIV ? inner + 1 : inner
}

function serializeCustom(editor: SlateEditor, node: Node): string {
  switch (node.type) {
    case QDIV: {
      const colons = ":".repeat(2 + divDepth(node))
      return `${colons} ${formatAttrs(node.attrs)}\n\n${serializeBlocks(editor, node.children)}\n\n${colons}`
    }
    case QTAB:
      return `${"#".repeat(node.level || 2)} ${node.title}\n\n${serializeBlocks(editor, node.children)}`
    case QCELL:
      return ["```{" + node.kind + "}", ...node.options, node.code, "```"].join("\n")
    case QFIGURE:
      return `![${node.caption}](${node.src})${hasAttrs(node.attrs) ? formatAttrs(node.attrs) : ""}`
    case QCAPTION:
      return `: ${node.text}`
    case QDETAILS:
      return `<details>\n<summary>${node.summary}</summary>\n\n${serializeBlocks(editor, node.children)}\n\n</details>`
    case EQUATION:
      return `$$\n${node.texExpression}\n$$${node.label ? ` {#${node.label}}` : ""}`
    default:
      return node.source ?? ""
  }
}

/** Plain Markdown nodes through Plate, with inline Pandoc syntax restored after. */
function markdownOf(editor: SlateEditor, nodes: Node[]): string {
  const sources: string[] = []
  const put = (source: string) => token(sources.push(source) - 1)
  const masked = nodes.map((node) => maskNode(node, put))
  const md = withAlignment(serializeMd(editor, { value: masked as never }), nodes)
  return (
    md
      .replace(TOKEN, (_, n) => sources[Number(n)])
      // Plate writes an empty table cell as a zero-width space.
      .replace(/​/g, "")
      // remark writes a bare e-mail address as <a@b.org>, which Pandoc reads the same but our
      // checker takes for an HTML tag.
      .replace(/<(?!mailto:|https?:)([^<>\s@]+@[^<>\s]+)>/g, "$1")
      .trimEnd()
  )
}

/** An inline element's marks (bold, italic, ...): its fields that aren't its content. */
function marksOfElement(node: Node): Node {
  const { type: _t, children: _c, kind: _k, source: _s, texExpression: _x, id: _i, ...marks } = node
  void [_t, _c, _k, _s, _x, _i]
  return marks
}

function maskNode(node: Node, put: (source: string) => string): Node {
  // Inline math is written by us rather than Plate, like citations, so that both keep their
  // marks: the token is a text with the element's marks, and remark writes the emphasis.
  if (node.type === QINLINE) return { ...marksOfElement(node), text: put(node.source) }
  if (node.type === INLINE_EQUATION) {
    return { ...marksOfElement(node), text: put(`$${node.texExpression}$`) }
  }
  // A newline in text is a hard break (soft ones were read as spaces); Plate writes it as a bare
  // newline in list items, which would read back as a space.
  if (typeof node.text === "string") {
    return node.text.includes("\n") ? { ...node, text: node.text.replace(/\n/g, () => put("\\\n")) } : node
  }
  if (!Array.isArray(node.children)) return node
  const children = (node.children as Node[]).map((c) => maskNode(c, put))
  if (HEADINGS.has(node.type) && hasAttrs(node[HEADING_ATTRS])) {
    children.push({ text: " " + put(formatAttrs(node[HEADING_ATTRS])) })
  }
  return { ...node, children }
}
