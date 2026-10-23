"use client";

import {
  ArrowDownIcon,
  ArrowUpIcon,
  ImageIcon,
  PlusIcon,
  Trash2Icon,
  TriangleAlertIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { EvidenceItem } from "@/lib/api";

import type { DraftBlock } from "./draft";
import { evidenceLabel } from "./revision-diff";

// The server's BlockKind (api/app/notes.py).
export const BLOCK_KINDS = [
  "overview",
  "definition",
  "theorem",
  "proof",
  "example",
  "intuition",
  "explanation",
  "remark",
  "summary",
] as const;

type BlockEditorProps = {
  index: number;
  count: number;
  block: DraftBlock;
  evidence: EvidenceItem[];
  onChange: (patch: Partial<DraftBlock>) => void;
  onMove: (delta: -1 | 1) => void;
  onRemove: () => void;
  onAddBelow: () => void;
  onInsertImage: () => void;
  onCaret: (position: number) => void;
};

/** Kind, title, Markdown/LaTeX content and evidence citations of one block. */
export function BlockEditor({
  index,
  count,
  block,
  evidence,
  onChange,
  onMove,
  onRemove,
  onAddBelow,
  onInsertImage,
  onCaret,
}: BlockEditorProps) {
  const name = `Block ${index + 1}${block.id ? ` (${block.id})` : " (new)"}`;
  const id = (field: string) => `block-${block.key}-${field}`;
  const known = new Set(evidence.map((item) => item.chunk_id));
  const foreign = block.citations.filter((chunk) => !known.has(chunk));

  const toggle = (chunk: string, on: boolean) =>
    onChange({
      citations: on
        ? [...block.citations.filter((c) => c !== chunk), chunk]
        : block.citations.filter((c) => c !== chunk),
    });

  return (
    <section aria-label={name} className="flex flex-col gap-3 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-medium">Block {index + 1}</h3>
        {block.id ? (
          <code className="text-xs text-muted-foreground">{block.id}</code>
        ) : (
          <Badge variant="secondary">New block</Badge>
        )}
        <div className="ml-auto flex gap-1">
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Move block up"
            disabled={index === 0}
            onClick={() => onMove(-1)}
          >
            <ArrowUpIcon />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Move block down"
            disabled={index === count - 1}
            onClick={() => onMove(1)}
          >
            <ArrowDownIcon />
          </Button>
          <Button variant="ghost" size="icon-sm" aria-label="Insert image" onClick={onInsertImage}>
            <ImageIcon />
          </Button>
          <Button variant="ghost" size="icon-sm" aria-label="Add block below" onClick={onAddBelow}>
            <PlusIcon />
          </Button>
          <Button variant="ghost" size="icon-sm" aria-label="Delete block" onClick={onRemove}>
            <Trash2Icon />
          </Button>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-[12rem_1fr]">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={id("kind")}>Kind</Label>
          <Select
            value={block.kind}
            onValueChange={(kind) => kind && onChange({ kind })}
            items={BLOCK_KINDS.map((kind) => ({ value: kind, label: kind }))}
          >
            <SelectTrigger id={id("kind")} aria-label="Kind" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {BLOCK_KINDS.map((kind) => (
                <SelectItem key={kind} value={kind}>
                  {kind}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={id("title")}>Title</Label>
          <Input
            id={id("title")}
            value={block.title ?? ""}
            placeholder="No title"
            onChange={(event) => onChange({ title: event.target.value })}
          />
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={id("content")}>Content (Markdown and LaTeX)</Label>
        <textarea
          id={id("content")}
          value={block.content}
          spellCheck={false}
          onChange={(event) => {
            onChange({ content: event.target.value });
            onCaret(event.target.selectionEnd);
          }}
          onSelect={(event) => onCaret(event.currentTarget.selectionEnd)}
          className="min-h-32 w-full rounded-lg border border-input bg-transparent px-2.5 py-2 font-mono text-sm leading-relaxed outline-none [field-sizing:content] focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
        />
      </div>

      <fieldset className="flex flex-col gap-1.5">
        <legend className="mb-1.5 text-sm font-medium">Citations</legend>
        {evidence.length === 0 && (
          <p className="text-xs text-muted-foreground">This topic has no evidence to cite.</p>
        )}
        {evidence.map((item) => (
          <label key={item.chunk_id} className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-0.5 size-4 accent-primary"
              checked={block.citations.includes(item.chunk_id)}
              onChange={(event) => toggle(item.chunk_id, event.target.checked)}
            />
            <span className="min-w-0">
              {evidenceLabel(item, item.chunk_id)}
              <span className="text-muted-foreground"> · {item.role} · </span>
              <code className="text-xs text-muted-foreground">{item.chunk_id}</code>
            </span>
          </label>
        ))}
        {foreign.map((chunk) => (
          <label key={chunk} className="flex items-start gap-2 text-sm text-warning">
            <input
              type="checkbox"
              className="mt-0.5 size-4 accent-primary"
              checked
              onChange={() => toggle(chunk, false)}
            />
            <span className="flex min-w-0 items-center gap-1">
              <TriangleAlertIcon className="size-3.5 shrink-0" />
              <code className="text-xs">{chunk}</code> isn&apos;t in this topic&apos;s evidence.
              Untick it to save.
            </span>
          </label>
        ))}
      </fieldset>
    </section>
  );
}
