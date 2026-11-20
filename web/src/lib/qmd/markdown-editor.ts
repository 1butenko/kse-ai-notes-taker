/** A headless Plate editor with the plugins the converter's Markdown needs. The editing UI
 * uses React versions of the same plugins, so their nodes are the same. */

import { BaseBasicBlocksPlugin, BaseBasicMarksPlugin } from "@platejs/basic-nodes"
import { BaseCodeBlockPlugin } from "@platejs/code-block"
import { BaseLinkPlugin } from "@platejs/link"
import { BaseListPlugin } from "@platejs/list"
import { MarkdownPlugin } from "@platejs/markdown"
import { BaseEquationPlugin, BaseInlineEquationPlugin } from "@platejs/math"
import { BaseTablePlugin } from "@platejs/table"
import { createSlateEditor } from "platejs"
import remarkGfm from "remark-gfm"
import remarkMath from "remark-math"

type MdNode = { type: string; value?: string; children?: MdNode[] }

/** A soft line break (a newline inside a paragraph) is a space; Plate would read it as a hard
 * break and write it back as `\`. Real hard breaks are `break` nodes and stay. */
function remarkSoftBreaks() {
  const walk = (node: MdNode) => {
    if (node.type === "text" && node.value) node.value = node.value.replace(/[ \t]*\n[ \t]*/g, " ")
    node.children?.forEach(walk)
  }
  return walk
}

export const markdownPlugin = MarkdownPlugin.configure({
  options: {
    remarkPlugins: [remarkGfm, remarkMath, remarkSoftBreaks],
    remarkStringifyOptions: { bullet: "-", emphasis: "*", rule: "*" },
  },
})

export function createMarkdownEditor() {
  return createSlateEditor({
    plugins: [
      BaseBasicBlocksPlugin,
      BaseBasicMarksPlugin,
      BaseListPlugin,
      BaseTablePlugin,
      BaseCodeBlockPlugin,
      BaseLinkPlugin,
      BaseEquationPlugin,
      BaseInlineEquationPlugin,
      markdownPlugin,
    ],
  })
}
