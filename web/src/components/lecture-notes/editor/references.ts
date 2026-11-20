"use client";

/** Cross-references in the editor: what an `@id` reads as on the published page, and renaming
 * an id together with every `@id` that points at it. */

import { useEditorRef } from "platejs/react";

import { definedIds, kindOfId, referencesTo } from "@/lib/qmd/ids";
import { HEADING_ATTRS, XREF_PREFIXES } from "@/lib/qmd/nodes";

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- Plate nodes are open records.
type Node = Record<string, any>;

/** Point every cross-reference at `from` to `to` instead. */
export function useRenameReferences() {
  const editor = useEditorRef();
  return (from: string | undefined, to: string | undefined) => {
    if (!from || !to || from === to) return;
    for (const [path, source] of referencesTo(editor.children as never, from, to)) {
      editor.tf.setNodes({ source }, { at: path });
    }
  };
}

/** "Section 2.1", "Definition 3", "Figure 1": an `@id` as Quarto numbers it. */
export function xrefLabel(nodes: Node[], id: string): string {
  const kind = kindOfId(id);
  if (id.startsWith("sec-")) {
    // Top-level headings, numbered by level from h2 down, as the published page does.
    const counters: number[] = [];
    for (const node of nodes) {
      const level = /^h([2-6])$/.exec(node.type)?.[1];
      if (!level) continue;
      const attrs = node[HEADING_ATTRS];
      if (attrs?.classes?.includes("unnumbered")) {
        if (attrs.id === id) return kind;
        continue;
      }
      const depth = Number(level) - 2;
      counters.length = depth + 1;
      counters[depth] = (counters[depth] ?? 0) + 1;
      if (attrs?.id === id) return `${kind} ${counters.map((n) => n ?? 1).join(".")}`;
    }
    return kind;
  }
  const prefix = XREF_PREFIXES.find((p) => id.startsWith(p));
  const same = definedIds(nodes).filter((d) => prefix && d.id.startsWith(prefix));
  const at = same.findIndex((d) => d.id === id);
  return at < 0 ? `${kind} ?` : `${kind} ${at + 1}`;
}
