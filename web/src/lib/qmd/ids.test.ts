import { describe, expect, test } from "vitest"

import { formatCitation, parseCitation } from "./citations"
import { parseQmd } from "./convert"
import { definedIds, idProblem, referencesTo } from "./ids"
import { createMarkdownEditor } from "./markdown-editor"

const editor = createMarkdownEditor()

describe("ids", () => {
  const nodes = parseQmd(
    editor,
    [
      "## Stretch {#sec-stretch}",
      "",
      "::: {#thm-char}",
      "## Characteristic equation",
      "Text.",
      ":::",
      "",
      "$$ a $$ {#eq-a}",
      "",
      "![A picture](assets/p.svg){#fig-p}",
      "",
      "```{dot}",
      "//| label: fig-g",
      '//| fig-cap: "A graph"',
      "digraph {}",
      "```",
      "",
      "| a |",
      "| - |",
      "| 1 |",
      "",
      ": Methods {#tbl-m}",
      "",
      "As @thm-char and [@thm-char; @r1] show, see @sec-stretch, not @thm-charm.",
    ].join("\n"),
  )

  test("every defined id, with its kind and text", () => {
    expect(definedIds(nodes)).toEqual([
      { id: "sec-stretch", kind: "Section", text: "Stretch" },
      { id: "thm-char", kind: "Theorem", text: "Characteristic equation" },
      { id: "eq-a", kind: "Equation", text: "a" },
      { id: "fig-p", kind: "Figure", text: "A picture" },
      { id: "fig-g", kind: "Figure", text: "A graph" },
      { id: "tbl-m", kind: "Table", text: "Methods" },
    ])
  })

  test("renaming finds every reference to that id only", () => {
    const renamed = referencesTo(nodes, "thm-char", "thm-eigen").map(([, source]) => source)
    expect(renamed).toEqual(["@thm-eigen", "[@thm-eigen; @r1]"])
  })

  test("new ids are checked", () => {
    expect(idProblem("thm-x", ["thm-"], [])).toBeNull()
    expect(idProblem("x", ["thm-"], [])).toMatch(/Start it/)
    expect(idProblem("thm-", ["thm-"], [])).toMatch(/Letters/)
    expect(idProblem("thm-a", ["thm-"], ["thm-a"])).toMatch(/already/)
  })
})

describe("citations", () => {
  test.each([
    "[@r1, p. 34]",
    "[@r1, p. 34; @r2]",
    "[see @r1, pp. 3-4]",
    "[-@r1]",
    "@r1",
  ])("%s reads and writes back", (source) => {
    expect(formatCitation(parseCitation(source)!)).toBe(source)
  })

  test("parts", () => {
    expect(parseCitation("[see @r1, p. 3; @r2]")).toEqual({
      bracketed: true,
      items: [
        { prefix: "see", key: "r1", suppress: false, locator: "p. 3" },
        { prefix: "", key: "r2", suppress: false, locator: "" },
      ],
    })
    expect(parseCitation("[no key here]")).toBeNull()
  })
})
