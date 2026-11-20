"use client";

/** Citations and cross-references: the editors behind them, opened by a click on one. */

import { useState } from "react";
import { PlusIcon, XIcon } from "lucide-react";
import { useEditorRef } from "platejs/react";

import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { type Citation, formatCitation, parseCitation } from "@/lib/qmd/citations";
import { definedIds } from "@/lib/qmd/ids";

import { useNotesEditor } from "./context";

/** The lecture's readings, to cite. */
export function ReferenceList({ onPick }: { onPick: (key: string) => void }) {
  const { source } = useNotesEditor();
  return (
    <Command>
      <CommandInput autoFocus placeholder="Find a reading…" />
      <CommandList className="max-h-64">
        <CommandEmpty>No such reading.</CommandEmpty>
        <CommandGroup heading="Readings">
          {source.references.map((r) => (
            <CommandItem key={r.id} value={r.id} keywords={[r.title]} onSelect={() => onPick(r.id)}>
              <span className="font-mono text-xs text-muted-foreground">{r.id}</span>
              <span className="truncate">{r.title}</span>
            </CommandItem>
          ))}
        </CommandGroup>
      </CommandList>
    </Command>
  );
}

/** The note's numbered blocks, to refer to. */
export function TargetList({ onPick }: { onPick: (id: string) => void }) {
  const editor = useEditorRef();
  const ids = definedIds(editor.children as never);
  const kinds = [...new Set(ids.map((d) => d.kind))];
  return (
    <Command>
      <CommandInput autoFocus placeholder="Find a section, figure, theorem…" />
      <CommandList className="max-h-64">
        <CommandEmpty>Nothing numbered to refer to yet.</CommandEmpty>
        {kinds.map((kind) => (
          <CommandGroup key={kind} heading={kind}>
            {ids
              .filter((d) => d.kind === kind)
              .map((d) => (
                <CommandItem key={d.id} value={d.id} keywords={[d.text]} onSelect={() => onPick(d.id)}>
                  <span className="truncate">{d.text || d.id}</span>
                  <span className="ml-auto font-mono text-xs text-muted-foreground">@{d.id}</span>
                </CommandItem>
              ))}
          </CommandGroup>
        ))}
      </CommandList>
    </Command>
  );
}

/** A citation's readings and page numbers. */
export function CitationEditor({
  citation,
  onChange,
}: {
  citation: Citation;
  onChange: (citation: Citation) => void;
}) {
  const { source } = useNotesEditor();
  const [adding, setAdding] = useState(false);
  const title = (key: string) => source.references.find((r) => r.id === key)?.title ?? "Unknown reading";
  const set = (i: number, locator: string) =>
    onChange({
      ...citation,
      items: citation.items.map((item, j) => (j === i ? { ...item, locator } : item)),
    });

  return (
    <div className="flex flex-col gap-3">
      <FieldGroup className="gap-3">
        {citation.items.map((item, i) => (
          <Field key={`${item.key}-${i}`}>
            <FieldLabel className="flex items-center justify-between gap-2">
              <span className="truncate">
                <span className="font-mono text-xs text-muted-foreground">{item.key}</span>{" "}
                {title(item.key)}
              </span>
              {citation.items.length > 1 && (
                <Button
                  variant="ghost"
                  size="icon-xs"
                  aria-label={`Remove ${item.key}`}
                  onClick={() =>
                    onChange({ ...citation, items: citation.items.filter((_, j) => j !== i) })
                  }
                >
                  <XIcon />
                </Button>
              )}
            </FieldLabel>
            <Input
              value={item.locator}
              placeholder="Page, e.g. p. 34"
              aria-label={`Page in ${item.key}`}
              onChange={(e) => set(i, e.target.value)}
            />
          </Field>
        ))}
      </FieldGroup>
      {adding ? (
        <ReferenceList
          onPick={(key) => {
            onChange({
              bracketed: true,
              items: [...citation.items, { prefix: "", key, suppress: false, locator: "" }],
            });
            setAdding(false);
          }}
        />
      ) : (
        <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
          <PlusIcon data-icon="inline-start" />
          Cite another reading
        </Button>
      )}
    </div>
  );
}

export { formatCitation, parseCitation };
