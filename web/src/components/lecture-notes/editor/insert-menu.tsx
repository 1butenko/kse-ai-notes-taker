"use client";

/** The menus typed in the text, as in Notion: "/" inserts a block, "@" cites a reading or
 * refers to a numbered block. Each searches as you type; Escape leaves the typed character. */

import type { SlateEditor } from "platejs";
import { useEditorRef } from "platejs/react";

import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent } from "@/components/ui/popover";
import { definedIds } from "@/lib/qmd/ids";
import { empty, QINLINE } from "@/lib/qmd/nodes";

import { INSERT_ITEMS, type InsertItem } from "./blocks";
import { useNotesEditor } from "./context";

const GROUPS = [...new Set(INSERT_ITEMS.map((i) => i.group))];

export type MenuTarget = {
  menu: "insert" | "mention";
  /** The block it was opened at. */
  path: number[];
  /** Where the "/" or "@" that opened it was typed; none from the gutter's "+". */
  at?: TPoint;
};

type Editor = SlateEditor;
type TPoint = { path: number[]; offset: number };

/** Remove the "/" or "@" typed at `at`, if it is still there. */
function removeTrigger(editor: Editor, at: TPoint | undefined, char: string) {
  if (!at) return;
  const range = { anchor: at, focus: { ...at, offset: at.offset + 1 } };
  try {
    if (editor.api.string(range) === char) editor.tf.delete({ at: range });
  } catch {
    // The text moved; leave it.
  }
}

/** Open "/" or "@" here? Only at the start of a word, and not in code. */
export function triggerAt(editor: Editor, key: string): MenuTarget | null {
  if (key !== "/" && key !== "@") return null;
  const { selection } = editor;
  if (!selection || editor.api.isExpanded()) return null;
  const entry = editor.api.block();
  if (!entry || entry[0].type === "code_line") return null;
  const before = editor.api.string({
    anchor: editor.api.start(entry[1])!,
    focus: selection.anchor,
  });
  if (before && !/\s$/.test(before)) return null;
  return { menu: key === "/" ? "insert" : "mention", path: entry[1], at: selection.anchor };
}

function useMenuAnchor(target: MenuTarget | null) {
  const editor = useEditorRef();
  if (!target) return undefined;
  if (target.at) {
    const at = target.at;
    return {
      getBoundingClientRect: () => {
        try {
          return editor.api.toDOMRange({ anchor: at, focus: at })!.getBoundingClientRect();
        } catch {
          return new DOMRect();
        }
      },
    };
  }
  const block = editor.api.node(target.path);
  return block ? editor.api.toDOMNode(block[0]) : undefined;
}

type MenuProps = { target: MenuTarget | null; onClose: () => void };

function MenuPopover({
  target,
  onClose,
  children,
  className,
}: MenuProps & { children: React.ReactNode; className?: string }) {
  const editor = useEditorRef();
  const anchor = useMenuAnchor(target);
  return (
    <Popover
      open={!!target && !!anchor}
      onOpenChange={(open) => {
        if (!open) {
          onClose();
          editor.tf.focus();
        }
      }}
    >
      <PopoverContent anchor={anchor} align="start" side="bottom" className={className}>
        {children}
      </PopoverContent>
    </Popover>
  );
}

export function InsertMenu({ target, onClose }: MenuProps) {
  const editor = useEditorRef();
  const open = target?.menu === "insert" ? target : null;

  const insert = (item: InsertItem) => {
    if (!open) return;
    const { path } = open;
    const made = item.make();
    const nodes = Array.isArray(made) ? made : [made];
    let at = path;
    editor.tf.withoutNormalizing(() => {
      removeTrigger(editor, open.at, "/");
      const block = editor.api.node(path);
      if (!block) return;
      const [node] = block;
      // An empty paragraph becomes the block; otherwise the block goes below.
      const isEmptyParagraph =
        node.type === "p" && !node.listStyleType && editor.api.string(path) === "";
      at = isEmptyParagraph ? path : [...path.slice(0, -1), path[path.length - 1] + 1];
      if (isEmptyParagraph) editor.tf.removeNodes({ at: path });
      editor.tf.insertNodes(nodes, { at });
    });
    onClose();
    // Put the cursor in the new block's first text.
    requestAnimationFrame(() => {
      editor.tf.focus();
      const start = editor.api.start(at);
      if (start) editor.tf.select(start);
    });
  };

  return (
    <MenuPopover target={open} onClose={onClose} className="w-72 p-0">
      <Command loop>
        <CommandInput autoFocus placeholder="Insert a block…" />
        <CommandList className="max-h-80">
          <CommandEmpty>No such block.</CommandEmpty>
          {GROUPS.map((group) => (
            <CommandGroup key={group} heading={group}>
              {INSERT_ITEMS.filter((i) => i.group === group).map((item) => (
                <CommandItem
                  key={item.key}
                  value={item.key}
                  keywords={[item.label, item.keywords ?? ""]}
                  onSelect={() => insert(item)}
                >
                  <item.icon />
                  {item.label}
                </CommandItem>
              ))}
            </CommandGroup>
          ))}
        </CommandList>
      </Command>
    </MenuPopover>
  );
}

export function MentionMenu({ target, onClose }: MenuProps) {
  const editor = useEditorRef();
  const { source } = useNotesEditor();
  const open = target?.menu === "mention" ? target : null;
  const ids = open ? definedIds(editor.children as never) : [];
  const kinds = [...new Set(ids.map((d) => d.kind))];

  const insert = (kind: "cite" | "xref", text: string) => {
    if (!open?.at) return;
    const at = open.at;
    editor.tf.withoutNormalizing(() => {
      removeTrigger(editor, at, "@");
      editor.tf.insertNodes({ type: QINLINE, kind, source: text, children: empty() } as never, {
        at,
        select: true,
      });
    });
    onClose();
    requestAnimationFrame(() => {
      editor.tf.focus();
      editor.tf.move({ unit: "offset" });
    });
  };

  return (
    <MenuPopover target={open} onClose={onClose} className="w-96 p-0">
      <Command loop>
        <CommandInput autoFocus placeholder="Cite a reading or refer to a block…" />
        <CommandList className="max-h-80">
          <CommandEmpty>Nothing matches.</CommandEmpty>
          {source.references.length > 0 && (
            <CommandGroup heading="Cite a reading">
              {source.references.map((r) => (
                <CommandItem
                  key={r.id}
                  value={`cite-${r.id}`}
                  keywords={[r.id, r.title]}
                  onSelect={() => insert("cite", `[@${r.id}]`)}
                >
                  <span className="truncate">{r.title}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          )}
          {kinds.map((kind) => (
            <CommandGroup key={kind} heading={`Refer to a ${kind.toLowerCase()}`}>
              {ids
                .filter((d) => d.kind === kind)
                .map((d) => (
                  <CommandItem
                    key={d.id}
                    value={`xref-${d.id}`}
                    keywords={[d.id, d.text]}
                    onSelect={() => insert("xref", `@${d.id}`)}
                  >
                    <span className="truncate">{d.text || d.id}</span>
                  </CommandItem>
                ))}
            </CommandGroup>
          ))}
        </CommandList>
      </Command>
    </MenuPopover>
  );
}
