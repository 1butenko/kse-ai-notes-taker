/** Pandoc attributes: `{#id .class key="value"}`, as on divs, headings, figures and spans. */

export type Attrs = {
  id?: string
  classes: string[]
  /** Other attributes, in their order: title, collapse, width, layout-ncol, ... */
  kv: [string, string][]
}

export const emptyAttrs = (): Attrs => ({ classes: [], kv: [] })

const TOKEN = /\.[\w-]+|#[\w:.-]+|[\w-]+=(?:"[^"]*"|'[^']*'|[^\s"']+)|\S+/g

/** Parse the inside of `{...}` (or the bare-class form `callout-note`). Null when it isn't
 * attributes. Mirrors `parse_attributes` in the API's validate.py. */
export function parseAttrs(text: string): Attrs | null {
  let inner = text.trim()
  if (inner.startsWith("{") && inner.endsWith("}")) inner = inner.slice(1, -1).trim()
  else if (!/^[.#]/.test(inner) && !inner.includes("=")) inner = "." + inner
  const attrs = emptyAttrs()
  for (const token of inner.match(TOKEN) ?? []) {
    if (token.startsWith(".")) attrs.classes.push(token.slice(1))
    else if (token.startsWith("#")) attrs.id = token.slice(1)
    else if (token.includes("=")) {
      const at = token.indexOf("=")
      attrs.kv.push([token.slice(0, at), token.slice(at + 1).replace(/^(["'])(.*)\1$/, "$2")])
    } else return null
  }
  return attrs
}

export function formatAttrs(attrs: Attrs): string {
  const parts = [
    ...(attrs.id ? [`#${attrs.id}`] : []),
    ...attrs.classes.map((c) => `.${c}`),
    ...attrs.kv.map(([k, v]) => `${k}="${v.replace(/"/g, "&quot;")}"`),
  ]
  return `{${parts.join(" ")}}`
}

export const hasAttrs = (attrs: Attrs | undefined): attrs is Attrs =>
  !!attrs && (!!attrs.id || attrs.classes.length > 0 || attrs.kv.length > 0)

export const attr = (attrs: Attrs, key: string): string | undefined =>
  attrs.kv.find(([k]) => k === key)?.[1]

export function withAttr(attrs: Attrs, key: string, value: string | undefined): Attrs {
  const kv = attrs.kv.filter(([k]) => k !== key)
  if (value !== undefined && value !== "") {
    const at = attrs.kv.findIndex(([k]) => k === key)
    kv.splice(at < 0 ? kv.length : at, 0, [key, value])
  }
  return { ...attrs, kv }
}
