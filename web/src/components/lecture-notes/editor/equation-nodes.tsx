"use client";

/** Display and inline math: drawn with KaTeX (the published page uses MathJax; both read the
 * same TeX); a click opens its TeX. An equation's `eq-` label is kept as it is. */

import katex from "katex";
import "katex/dist/katex.min.css";
import { useMemo, useState } from "react";
import { PlateElement, type PlateElementProps, useEditorRef, useSelected } from "platejs/react";

import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

function useTex(tex: string, displayMode: boolean) {
  return useMemo(() => {
    try {
      return { html: katex.renderToString(tex || "\\square", { displayMode, throwOnError: true }) };
    } catch (error) {
      return { error: error instanceof Error ? error.message : String(error) };
    }
  }, [tex, displayMode]);
}

function TexEditor({
  props,
  display,
}: {
  props: PlateElementProps;
  display: boolean;
}) {
  const editor = useEditorRef();
  const selected = useSelected();
  const tex = (props.element.texExpression as string) ?? "";
  const [open, setOpen] = useState(!tex);
  const rendered = useTex(tex, display);
  const set = (fields: Record<string, unknown>) =>
    editor.tf.setNodes(fields, { at: editor.api.findPath(props.element) });

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        nativeButton={false}
        render={
          <span
            className={cn(
              "cursor-pointer rounded-md transition-colors hover:bg-muted",
              display ? "flex items-center justify-center px-2 py-1" : "inline px-0.5",
              selected && "bg-muted",
            )}
          />
        }
      >
        {"html" in rendered ? (
          <span dangerouslySetInnerHTML={{ __html: rendered.html! }} />
        ) : (
          <span className="font-mono text-sm text-destructive">{tex || "empty"}</span>
        )}
      </PopoverTrigger>
      <PopoverContent className="w-96" align="start">
        <Field data-invalid={"error" in rendered || undefined}>
          <FieldLabel htmlFor={`tex-${props.element.id}`}>TeX</FieldLabel>
          <Textarea
            id={`tex-${props.element.id}`}
            autoFocus
            value={tex}
            rows={display ? 4 : 2}
            className="font-mono text-sm"
            aria-invalid={"error" in rendered || undefined}
            onChange={(e) => set({ texExpression: e.target.value })}
            onKeyDown={(e) => {
              if (e.key === "Escape" || (e.key === "Enter" && (e.metaKey || e.ctrlKey))) {
                e.preventDefault();
                setOpen(false);
                editor.tf.focus();
              }
            }}
          />
          {"error" in rendered && <FieldDescription>{rendered.error}</FieldDescription>}
        </Field>
      </PopoverContent>
    </Popover>
  );
}

export function EquationElement(props: PlateElementProps) {
  return (
    <PlateElement {...props} className="my-4">
      <div contentEditable={false}>
        <TexEditor props={props} display />
      </div>
      {props.children}
    </PlateElement>
  );
}

export function InlineEquationElement(props: PlateElementProps) {
  return (
    <PlateElement {...props} as="span" className="inline">
      <span contentEditable={false}>
        <TexEditor props={props} display={false} />
      </span>
      {props.children}
    </PlateElement>
  );
}
