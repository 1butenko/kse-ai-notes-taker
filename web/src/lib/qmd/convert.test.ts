import { readdirSync, readFileSync, writeFileSync, mkdirSync } from "node:fs"
import path from "node:path"

import { describe, expect, test } from "vitest"

import { parseQmd, serializeQmd } from "./convert"
import { createMarkdownEditor } from "./markdown-editor"

const editor = createMarkdownEditor()
const parse = (body: string) => parseQmd(editor, body)
const roundTrip = (body: string) => serializeQmd(editor, parse(body))

const FIXTURES = path.join(import.meta.dirname, "fixtures")
const fixtures = readdirSync(FIXTURES).filter((f) => f.endsWith(".qmd"))
// Set QMD_ROUNDTRIP_DIR to write the round-tripped fixtures there, to run the API's
// validate_body over them.
const OUT = process.env.QMD_ROUNDTRIP_DIR

// Pandoc reads width=70% and width="70%" alike; we always quote.
const normalize = (s: string) => s.replace(/\s+/g, " ").replace(/"/g, "")

/** What Pandoc reads differently if it went missing: every Pandoc-only token in the source. */
function pandocTokens(body: string): string[] {
  return [
    ...body.matchAll(/\[[^[\]]*@[^[\]]*\]|(?<![\w@])-?@[\w][\w:.-]*\w|\{[#.][^{}]*\}|```\{\w+\}/g),
  ].map((m) => normalize(m[0]))
}

describe("skill examples", () => {
  test.each(fixtures)("%s round-trips", (name) => {
    const body = readFileSync(path.join(FIXTURES, name), "utf-8")
    const once = roundTrip(body)
    // Stable: what we write reads back to the same nodes and writes the same text.
    expect(parse(once)).toEqual(parse(body))
    expect(roundTrip(once)).toBe(once)
    // Nothing Pandoc-specific is lost or escaped.
    for (const t of pandocTokens(body)) expect(normalize(once)).toContain(t)
    expect(once).not.toMatch(/\\\[@|\\@|QMDK|⟦/)
    if (OUT) {
      mkdirSync(OUT, { recursive: true })
      writeFileSync(path.join(OUT, name), once)
    }
  })

  test("no example falls back to raw text", () => {
    for (const name of fixtures) {
      const body = readFileSync(path.join(FIXTURES, name), "utf-8")
      expect(JSON.stringify(parse(body)), name).not.toContain('"qraw"')
    }
  })
})

// Set QMD_REAL_DIR to a folder of published notes' bodies (*.qmd) to round-trip them too.
const REAL = process.env.QMD_REAL_DIR;
describe.skipIf(!REAL)("real notes", () => {
  const files = REAL ? readdirSync(REAL).filter((f) => f.endsWith(".qmd")) : [];
  test.each(files)("%s round-trips", (name) => {
    const body = readFileSync(path.join(REAL!, name), "utf-8")
    const once = roundTrip(body)
    expect(parse(once)).toEqual(parse(body))
    expect(roundTrip(once)).toBe(once)
    for (const t of pandocTokens(body)) expect(normalize(once)).toContain(t)
    expect(once).not.toMatch(/\\\[@|\\@|QMDK|⟦/)
    if (OUT) {
      mkdirSync(OUT, { recursive: true })
      writeFileSync(path.join(OUT, name), once)
    }
  })
})

describe("nodes", () => {
  test("callout with attributes and nested theorem", () => {
    const [div] = parse(
      ':::: {.callout-note collapse="true" title="Solution"}\n\n::: {#thm-a}\n## Name\n\nBody $x$.\n:::\n\n::::\n'
    )
    expect(div.type).toBe("qdiv")
    expect(div.attrs).toEqual({
      classes: ["callout-note"],
      kv: [
        ["collapse", "true"],
        ["title", "Solution"],
      ],
    })
    expect(div.children[0]).toMatchObject({ type: "qdiv", attrs: { id: "thm-a" } })
  })

  test("cells keep their options", () => {
    const [cell] = parse("```{dot}\n//| label: fig-g\n//| fig-cap: A graph\ndigraph { a -> b }\n```\n")
    expect(cell).toMatchObject({
      type: "qcell",
      kind: "dot",
      options: ["//| label: fig-g", "//| fig-cap: A graph"],
      code: "digraph { a -> b }",
    })
  })

  test("labelled display math, one line and several", () => {
    expect(parse("$$ a = b $$ {#eq-ab}\n")[0]).toMatchObject({
      type: "equation",
      texExpression: "a = b",
      label: "eq-ab",
    })
    expect(parse("$$\na\n+ b\n$$ {#eq-c}\n")[0]).toMatchObject({ texExpression: "a\n+ b" })
    expect(roundTrip("$$ a = b $$ {#eq-ab}\n")).toBe("$$\na = b\n$$ {#eq-ab}\n")
  })

  test("citations, cross-references and spans are inline nodes", () => {
    const [p] = parse("See @thm-a and [@r1, p. 3; @r2] or @r1, [key]{.mark}. Mail a@b.org.\n")
    const inline = p.children.filter((c: { type?: string }) => c.type === "qinline")
    expect(inline.map((c: { kind: string; source: string }) => [c.kind, c.source])).toEqual([
      ["xref", "@thm-a"],
      ["cite", "[@r1, p. 3; @r2]"],
      ["cite", "@r1"],
      ["span", "[key]{.mark}"],
    ])
    expect(roundTrip("See @thm-a and [@r1, p. 3; @r2] or @r1, [key]{.mark}. Mail a@b.org.\n")).toBe(
      "See @thm-a and [@r1, p. 3; @r2] or @r1, [key]{.mark}. Mail a@b.org.\n"
    )
  })

  test("a citation next to bold text", () => {
    const body = "**Step 3. Read it from** @eq-m**.** Next.\n"
    expect(roundTrip(body)).toBe(body)
  })

  test("a | in table math doesn't split the cell", () => {
    const body = "| a | b |\n| - | - |\n| MAE | $\\sum|e_t| + \\|x\\|$ |\n"
    const out = roundTrip(body)
    expect(out).toContain("$\\sum\\vert e_t\\vert + \\Vert x\\Vert$")
    const table = parse(body)[0]
    expect(table.children[1].children).toHaveLength(2)
  })

  test("table column alignment is kept", () => {
    const out = roundTrip("| a | b | c |\n|---|---:|:-:|\n| 1 | 2 | 3 |\n")
    expect(out.split("\n")[1]).toMatch(/^\| -+ \| -+: \| :-+: \|$/)
  })

  test("a soft line break stays a space, a hard one stays a break", () => {
    expect(roundTrip("One\ntwo.\n")).toBe("One two.\n")
    expect(roundTrip("One\\\ntwo.\n")).toBe("One\\\ntwo.\n")
  })

  test("bullets are written with -", () => {
    expect(roundTrip("* a\n* b\n")).toBe("- a\n- b\n")
  })

  test("@ in code and math is left alone", () => {
    const [p] = parse("Run `git@host` and $a@b$.\n")
    expect(JSON.stringify(p)).not.toContain("qinline")
  })

  test("heading attributes", () => {
    const [h] = parse("## Stretch {#sec-stretch .unnumbered}\n")
    expect(h).toMatchObject({
      type: "h2",
      attrs: { id: "sec-stretch", classes: ["unnumbered"] },
      children: [{ text: "Stretch" }],
    })
    expect(roundTrip("## Stretch {#sec-stretch .unnumbered}\n")).toBe(
      "## Stretch {#sec-stretch .unnumbered}\n"
    )
  })

  test("figures and table captions", () => {
    const body =
      "![Projection of $b$](assets/p.svg){#fig-p width=70%}\n\n| a | b |\n| - | - |\n| 1 | 2 |\n\n: Methods {#tbl-m}\n"
    const nodes = parse(body)
    expect(nodes[0]).toMatchObject({
      type: "qfigure",
      src: "assets/p.svg",
      caption: "Projection of $b$",
      attrs: { id: "fig-p", kv: [["width", "70%"]] },
    })
    expect(nodes.at(-1)).toMatchObject({ type: "qcaption", text: "Methods {#tbl-m}" })
  })

  test("a tabset becomes tabs", () => {
    const [div] = parse(
      '::: {.panel-tabset group="v"}\n## One\n\nFirst\n\n### Sub\n\nx\n\n## Two\n\n```{dot}\ndigraph {}\n```\n:::\n'
    )
    expect(div.children.map((t: { type: string; title: string }) => [t.type, t.title])).toEqual([
      ["qtab", "One"],
      ["qtab", "Two"],
    ])
    expect(div.children[0].children.map((n: { type: string }) => n.type)).toEqual(["p", "h3", "p"])
    expect(div.children[1].children[0].type).toBe("qcell")
  })

  test("details", () => {
    const [d] = parse("<details>\n<summary>Proof</summary>\n\nBecause.\n\n</details>\n")
    expect(d).toMatchObject({ type: "qdetails", summary: "Proof" })
  })

  test("what can't be placed is kept verbatim", () => {
    const body = "- item\n\n  ::: {.callout-note}\n  x\n  :::\n\nAfter\n"
    expect(parse(body).map((n) => n.type)).toEqual(["p", "qraw", "p"])
    expect(roundTrip(body)).toContain("  ::: {.callout-note}\n  x\n  :::")
    expect(parse("::: {.callout-note}\nnever closed\n")[0].type).toBe("qraw")
  })

  test("nesting gets enough colons", () => {
    const out = roundTrip(":::: {.columns}\n::: {.column}\nA\n:::\n::: {.column}\nB\n:::\n::::\n")
    expect(out.split("\n")[0]).toBe(":::: {.columns}")
    expect(out).toContain("::: {.column}\n\nA\n\n:::")
  })
})
