"use client";

/** The toolbar over selected text, as in Notion: bold, italic, strikethrough, code, link and
 * math. Everything else is typed: Markdown shortcuts (`## `, `- `, `**bold**`, `$x$`), "/" for
 * blocks and "@" for citations and references. */

import { useState } from "react";
import { insertInlineEquation } from "@platejs/math";
import {
  BoldIcon,
  CodeIcon,
  ItalicIcon,
  LinkIcon,
  type LucideIcon,
  SigmaIcon,
  StrikethroughIcon,
} from "lucide-react";
import { useEditorRef, useEditorSelector } from "platejs/react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent } from "@/components/ui/popover";
import { Separator } from "@/components/ui/separator";
import { Toggle } from "@/components/ui/toggle";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

const MARKS: { key: string; label: string; icon: LucideIcon }[] = [
  { key: "bold", label: "Bold (Ctrl+B)", icon: BoldIcon },
  { key: "italic", label: "Italic (Ctrl+I)", icon: ItalicIcon },
  { key: "strikethrough", label: "Strikethrough", icon: StrikethroughIcon },
  { key: "code", label: "Code (Ctrl+E)", icon: CodeIcon },
];

/** Keep the editor's selection when a toolbar control is pressed. */
const keepSelection = (e: React.MouseEvent) => e.preventDefault();

function Tip({ label, children }: { label: string; children: React.ReactElement }) {
  return (
    <Tooltip>
      <TooltipTrigger render={children} />
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

type SelectionToolbarProps = {
  /** Show the link field (Ctrl+K). */
  linking: boolean;
  onLinkingChange: (linking: boolean) => void;
};

export function SelectionToolbar({ linking, onLinkingChange }: SelectionToolbarProps) {
  const editor = useEditorRef();
  // Over selected text only, not over a selected figure or equation.
  const open = useEditorSelector(
    (e) => !!e.selection && e.api.isExpanded() && e.api.string(e.selection).trim() !== "",
    [],
  );
  const marks = useEditorSelector((e) => (e.api.marks() ?? {}) as Record<string, unknown>, []);
  const inCode = useEditorSelector((e) => e.api.block()?.[0].type === "code_line", []);

  const anchor = {
    getBoundingClientRect: () =>
      (editor.selection && editor.api.toDOMRange(editor.selection)?.getBoundingClientRect()) ||
      new DOMRect(),
  };

  if (inCode) return null;
  return (
    <Popover open={open || linking} onOpenChange={(o) => !o && onLinkingChange(false)}>
      <PopoverContent
        anchor={anchor}
        side="top"
        sideOffset={8}
        initialFocus={false}
        finalFocus={false}
        className="w-auto flex-row items-center gap-0.5 p-1"
      >
        {linking ? (
          <LinkField onDone={() => onLinkingChange(false)} />
        ) : (
          <>
            {MARKS.map(({ key, label, icon: Icon }) => (
              <Tip key={key} label={label}>
                <Toggle
                  size="sm"
                  aria-label={label}
                  pressed={!!marks[key]}
                  onMouseDown={keepSelection}
                  onPressedChange={() => editor.tf.toggleMark(key)}
                >
                  <Icon />
                </Toggle>
              </Tip>
            ))}
            <Separator orientation="vertical" className="mx-0.5 h-5" />
            <Tip label="Link (Ctrl+K)">
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Link"
                onMouseDown={keepSelection}
                onClick={() => onLinkingChange(true)}
              >
                <LinkIcon />
              </Button>
            </Tip>
            <Tip label="Math ($…$)">
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Math"
                onMouseDown={keepSelection}
                onClick={() => insertInlineEquation(editor)}
              >
                <SigmaIcon />
              </Button>
            </Tip>
          </>
        )}
      </PopoverContent>
    </Popover>
  );
}

function LinkField({ onDone }: { onDone: () => void }) {
  const editor = useEditorRef();
  const [url, setUrl] = useState("https://");
  const apply = () => {
    if (/^(https?:\/\/.+|mailto:.+|#.+)/.test(url)) {
      editor.tf.focus();
      editor.tf.wrapNodes({ type: "a", url, children: [] }, { split: true });
    }
    onDone();
  };
  return (
    <Input
      autoFocus
      value={url}
      aria-label="Link address"
      placeholder="Paste a link and press Enter"
      className="h-7 w-72"
      onChange={(e) => setUrl(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          apply();
        } else if (e.key === "Escape") {
          e.preventDefault();
          onDone();
          editor.tf.focus();
        }
      }}
      onBlur={onDone}
    />
  );
}
