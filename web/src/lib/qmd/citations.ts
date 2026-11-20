/** Pandoc citations as editable parts: `[@r1, p. 34; @r2]` or `@r1` (in text). */

export type CiteItem = {
  /** Text before the key inside the brackets: `see`. */
  prefix: string
  key: string
  /** `-@r1`: the year only (no author). */
  suppress: boolean
  /** After the key: `p. 34`. */
  locator: string
}

export type Citation = { bracketed: boolean; items: CiteItem[] }

const ITEM = /^(.*?)(-?)@([\w][\w:.#$%&+?<>~/-]*?)(?:,\s*(.*))?$/

/** The parts of a citation, or null when it isn't one we can edit as parts. */
export function parseCitation(source: string): Citation | null {
  const s = source.trim()
  if (!s.startsWith("[")) {
    const m = s.match(/^(-?)@([\w][\w:.-]*)$/)
    return m ? { bracketed: false, items: [{ prefix: "", key: m[2], suppress: !!m[1], locator: "" }] } : null
  }
  if (!s.endsWith("]")) return null
  const items: CiteItem[] = []
  for (const part of s.slice(1, -1).split(";")) {
    const m = part.trim().match(ITEM)
    if (!m) return null
    items.push({ prefix: m[1].trim(), suppress: !!m[2], key: m[3], locator: (m[4] ?? "").trim() })
  }
  return items.length ? { bracketed: true, items } : null
}

export function formatCitation({ bracketed, items }: Citation): string {
  const one = (i: CiteItem) =>
    `${i.prefix ? i.prefix + " " : ""}${i.suppress ? "-" : ""}@${i.key}${i.locator ? ", " + i.locator : ""}`
  if (!bracketed && items.length === 1 && !items[0].prefix && !items[0].locator) return one(items[0])
  return `[${items.map(one).join("; ")}]`
}
