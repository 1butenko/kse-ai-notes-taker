"use client";

/** The Quarto-only nodes in the editor (see `@/lib/qmd/nodes`), drawn as on the published page
 * (`notes-editor.css`) and edited in place: a callout's title is typed on the card, its icon picks
 * the kind; a theorem's label picks its kind; captions are typed under the figure. Ids, classes
 * and options the page doesn't show are kept as they are. */

import { Children, useRef, useState } from "react";
import {
  ChartSplineIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CircleAlertIcon,
  CodeIcon,
  GraduationCapIcon,
  ImageUpIcon,
  InfoIcon,
  LightbulbIcon,
  type LucideIcon,
  OctagonAlertIcon,
  PlusIcon,
  TriangleAlertIcon,
} from "lucide-react";
import { PlateElement, type PlateElementProps, useEditorRef, useSelected } from "platejs/react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Toggle } from "@/components/ui/toggle";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { type Attrs, attr, withAttr } from "@/lib/qmd/attrs";
import { formatCitation, parseCitation } from "@/lib/qmd/citations";
import { empty, type InlineKind, QTAB, THEOREM_KINDS } from "@/lib/qmd/nodes";
import { cn } from "@/lib/utils";

import { useNotesEditor } from "./context";
import { DiagramPreview } from "./diagram-preview";
import { CitationEditor, TargetList } from "./inline-pickers";
import { useRenameReferences, xrefLabel } from "./references";

type Element = PlateElementProps["element"];

/** Set fields on this element. */
function useSetNode(element: Element) {
  const editor = useEditorRef();
  return (fields: Record<string, unknown>) =>
    editor.tf.setNodes(fields, { at: editor.api.findPath(element) });
}

/** Controls inside the editor: not part of the editable text. */
function Controls({ className, ...props }: React.ComponentProps<"div">) {
  return <div contentEditable={false} className={cn("select-none", className)} {...props} />;
}

/** A field that reads as the page's own text (a title, a caption) until it is typed in. */
function TextField({ className, ...props }: React.ComponentProps<typeof Input>) {
  return (
    <Input
      className={cn(
        "h-auto rounded-none border-0 bg-transparent p-0 shadow-none focus-visible:ring-0 md:text-[length:inherit] dark:bg-transparent",
        "text-[length:inherit] placeholder:text-muted-foreground/60",
        className,
      )}
      {...props}
    />
  );
}

/** A caption under a figure or diagram, as long as it needs; its placeholder shows on hover. */
function CaptionField({ className, ...props }: React.ComponentProps<typeof Textarea>) {
  return (
    <Textarea
      rows={1}
      placeholder="Add a caption"
      aria-label="Caption"
      className={cn(
        "kse-caption mt-2 min-h-0 resize-none rounded-none border-0 bg-transparent p-0 text-center text-[0.9rem] shadow-none focus-visible:ring-0 md:text-[0.9rem] dark:bg-transparent",
        "placeholder:text-transparent group-hover/figure:placeholder:text-muted-foreground/60 focus:placeholder:text-muted-foreground/60",
        className,
      )}
      {...props}
    />
  );
}

// Divs

export const CALLOUTS: Record<string, { label: string; icon: LucideIcon }> = {
  "callout-note": { label: "Note", icon: InfoIcon },
  "callout-tip": { label: "Tip", icon: LightbulbIcon },
  "callout-important": { label: "Important", icon: CircleAlertIcon },
  "callout-warning": { label: "Warning", icon: TriangleAlertIcon },
  "callout-caution": { label: "Caution", icon: OctagonAlertIcon },
};

type DivKind = "callout" | "theorem" | "tabs" | "columns" | "column" | "margin" | "other";

function kindOf(attrs: Attrs): DivKind {
  if (attrs.classes.some((c) => c in CALLOUTS)) return "callout";
  if (attrs.id && Object.keys(THEOREM_KINDS).some((p) => attrs.id!.startsWith(p))) return "theorem";
  if (attrs.classes.includes("panel-tabset")) return "tabs";
  if (attrs.classes.includes("columns")) return "columns";
  if (attrs.classes.includes("column")) return "column";
  if (attrs.classes.some((c) => c === "column-margin" || c === "aside")) return "margin";
  return "other";
}

function Callout(props: PlateElementProps) {
  const set = useSetNode(props.element);
  const attrs = props.element.attrs as Attrs;
  const type = attrs.classes.find((c) => c in CALLOUTS)!;
  const goals = attrs.classes.includes("learning-goals");
  const collapsed = attr(attrs, "collapse") === "true";
  const Icon = goals ? GraduationCapIcon : CALLOUTS[type].icon;
  const setAttrs = (next: Attrs) => set({ attrs: next });

  return (
    <PlateElement
      {...props}
      className={cn("group/callout kse-callout", `kse-${type}`, goals && "learning-goals")}
    >
      <Controls className="flex items-center gap-3">
        <DropdownMenu>
          <Tooltip>
            <TooltipTrigger
              render={
                <DropdownMenuTrigger
                  render={
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label="Callout type"
                      className="kse-callout-icon shrink-0 rounded-[0.6rem]"
                    />
                  }
                />
              }
            >
              <Icon />
            </TooltipTrigger>
            <TooltipContent>{goals ? "Learning goals" : CALLOUTS[type].label}</TooltipContent>
          </Tooltip>
          <DropdownMenuContent align="start" className="w-40">
            <DropdownMenuGroup>
              {Object.entries(CALLOUTS).map(([value, { label, icon: ItemIcon }]) => (
                <DropdownMenuItem
                  key={value}
                  onClick={() =>
                    setAttrs({
                      ...attrs,
                      classes: attrs.classes.map((c) => (c in CALLOUTS ? value : c)),
                    })
                  }
                >
                  <ItemIcon />
                  {label}
                </DropdownMenuItem>
              ))}
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
        <TextField
          value={attr(attrs, "title") ?? ""}
          placeholder={goals ? "What you will learn" : "Add a title"}
          aria-label="Callout title"
          className="min-w-0 flex-1 font-medium"
          onChange={(e) => setAttrs(withAttr(attrs, "title", e.target.value || undefined))}
        />
        <Tooltip>
          <TooltipTrigger
            render={
              <Toggle
                size="sm"
                aria-label="Collapsed on the page"
                pressed={collapsed}
                onPressedChange={(on) =>
                  setAttrs(withAttr(attrs, "collapse", on ? "true" : undefined))
                }
                className={cn(!collapsed && "opacity-0 group-hover/callout:opacity-100")}
              />
            }
          >
            <ChevronDownIcon />
          </TooltipTrigger>
          <TooltipContent>
            {collapsed ? "Collapsed on the page: readers open it" : "Collapse it on the page"}
          </TooltipContent>
        </Tooltip>
      </Controls>
      <div className="kse-callout-body">{props.children}</div>
    </PlateElement>
  );
}

function Theorem(props: PlateElementProps) {
  const set = useSetNode(props.element);
  const rename = useRenameReferences();
  const attrs = props.element.attrs as Attrs;
  const prefix = Object.keys(THEOREM_KINDS).find((p) => attrs.id!.startsWith(p))!;

  return (
    <PlateElement {...props} className={cn("kse-theorem", `kse-theorem-${prefix.slice(0, -1)}`)}>
      <div className="kse-theorem-body">
        <span contentEditable={false} className="kse-theorem-label mr-1 select-none">
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button
                  variant="link"
                  className="h-auto p-0 align-baseline text-[length:inherit] font-bold text-foreground"
                />
              }
            >
              <span className="kse-theorem-number">{THEOREM_KINDS[prefix]}</span>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-40">
              <DropdownMenuGroup>
                {Object.entries(THEOREM_KINDS).map(([value, label]) => (
                  <DropdownMenuItem
                    key={value}
                    onClick={() => {
                      if (value === prefix) return;
                      const id = value + attrs.id!.slice(prefix.length);
                      rename(attrs.id, id);
                      set({ attrs: { ...attrs, id } });
                    }}
                  >
                    {label}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        </span>
        {props.children}
      </div>
    </PlateElement>
  );
}

function TabsDiv(props: PlateElementProps) {
  const editor = useEditorRef();
  const [active, setActive] = useState(0);
  const [renaming, setRenaming] = useState<number | null>(null);
  const tabs = props.element.children as Element[];
  const current = Math.min(active, tabs.length - 1);
  const path = () => editor.api.findPath(props.element)!;

  const rename = (i: number, title: string) => {
    setRenaming(null);
    if (title.trim()) {
      editor.tf.setNodes({ title: title.trim() }, { at: [...path(), i] });
    } else if (tabs.length > 1) {
      // A tab whose name is cleared goes, with its content.
      editor.tf.removeNodes({ at: [...path(), i] });
      setActive(Math.max(0, i - 1));
    }
  };

  return (
    <PlateElement {...props} className="group/tabs my-6">
      <Controls className="flex items-center gap-1">
        <Tabs value={current} onValueChange={(v) => setActive(Number(v))}>
          <TabsList>
            {tabs.map((tab, i) =>
              renaming === i ? (
                <Input
                  key={i}
                  autoFocus
                  defaultValue={tab.title as string}
                  aria-label="Tab name"
                  className="h-7 w-36"
                  onBlur={(e) => rename(i, e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") rename(i, e.currentTarget.value);
                    if (e.key === "Escape") setRenaming(null);
                  }}
                />
              ) : (
                <TabsTrigger
                  key={i}
                  value={i}
                  title="Double-click to rename"
                  onDoubleClick={() => setRenaming(i)}
                >
                  {(tab.title as string) || "Untitled"}
                </TabsTrigger>
              ),
            )}
          </TabsList>
        </Tabs>
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Add a tab"
                className="opacity-0 group-hover/tabs:opacity-100 focus-visible:opacity-100"
                onClick={() => {
                  editor.tf.insertNodes(
                    {
                      type: QTAB,
                      title: "New tab",
                      level: (tabs[0]?.level as number) ?? 2,
                      children: [{ type: "p", children: [{ text: "" }] }],
                    } as never,
                    { at: [...path(), tabs.length] },
                  );
                  setActive(tabs.length);
                  setRenaming(tabs.length);
                }}
              />
            }
          >
            <PlusIcon />
          </TooltipTrigger>
          <TooltipContent>Add a tab</TooltipContent>
        </Tooltip>
      </Controls>
      {/* Every tab stays in the document (and the DOM); only the chosen one shows. */}
      <div className="kse-tab-panel">
        {Children.toArray(props.children).map((child, i) => (
          <div key={i} hidden={i !== current}>
            {child}
          </div>
        ))}
      </div>
    </PlateElement>
  );
}

export function QDivElement(props: PlateElementProps) {
  const kind = kindOf(props.element.attrs as Attrs);
  if (kind === "callout") return <Callout {...props} />;
  if (kind === "theorem") return <Theorem {...props} />;
  if (kind === "tabs") return <TabsDiv {...props} />;
  return (
    <PlateElement
      {...props}
      className={cn(
        kind === "columns" && "my-4 flex gap-6",
        kind === "column" && "min-w-0 flex-1",
        kind === "margin" && "kse-margin my-2 ml-auto max-w-xs border-l pl-3",
      )}
    >
      {props.children}
    </PlateElement>
  );
}

export function QTabElement(props: PlateElementProps) {
  return <PlateElement {...props}>{props.children}</PlateElement>;
}

export function QDetailsElement(props: PlateElementProps) {
  const set = useSetNode(props.element);
  return (
    <PlateElement {...props} className="kse-details">
      <Controls className="mb-2 flex items-center gap-1.5">
        <ChevronRightIcon className="size-4 shrink-0 text-muted-foreground" />
        <TextField
          value={props.element.summary as string}
          placeholder="Summary"
          aria-label="Summary"
          className="font-medium"
          onChange={(e) => set({ summary: e.target.value })}
        />
      </Controls>
      {props.children}
    </PlateElement>
  );
}

// Cells

const OPTION_PREFIX = { dot: "//|", mermaid: "%%|", ojs: "//|" };
const OPTION = /^(\s*(?:#\||\/\/\||%%\|))\s*([\w-]+)\s*:\s*(.*?)\s*$/;

function optionOf(options: string[], key: string): string {
  const line = options.find((o) => o.match(OPTION)?.[2] === key);
  return line?.match(OPTION)?.[3].replace(/^(["'])(.*)\1$/, "$2") ?? "";
}

function withOption(options: string[], prefix: string, key: string, value: string): string[] {
  const at = options.findIndex((o) => o.match(OPTION)?.[2] === key);
  const quoted = /[:#"']|^\s|\s$/.test(value) ? JSON.stringify(value) : value;
  const line = `${options[at]?.match(OPTION)?.[1] ?? prefix} ${key}: ${quoted}`;
  if (!value) return options.filter((_, i) => i !== at);
  return at < 0 ? [...options, line] : options.map((o, i) => (i === at ? line : o));
}

/** A ghost button in a figure's top-right corner, shown on hover. */
function CornerButton(props: React.ComponentProps<typeof Button>) {
  return (
    <Button
      variant="secondary"
      size="xs"
      className="absolute top-2 right-2 opacity-0 group-hover/figure:opacity-100 focus-visible:opacity-100"
      {...props}
    />
  );
}

export function QCellElement(props: PlateElementProps) {
  const set = useSetNode(props.element);
  const selected = useSelected();
  const kind = props.element.kind as keyof typeof OPTION_PREFIX;
  const options = props.element.options as string[];
  const code = props.element.code as string;
  const [showCode, setShowCode] = useState(!code.trim());
  const prefix = OPTION_PREFIX[kind];

  return (
    <PlateElement {...props} className="kse-figure">
      <Controls
        className={cn("group/figure relative rounded-lg", selected && "ring-2 ring-ring/30")}
      >
        {kind === "ojs" ? (
          // Observable runs only on the published page.
          <div className="flex h-28 flex-col items-center justify-center gap-1 rounded-lg bg-muted/60 text-sm text-muted-foreground">
            <ChartSplineIcon className="size-5" />
            Interactive chart: it runs on the published page
          </div>
        ) : (
          <DiagramPreview kind={kind} code={code} />
        )}
        <CornerButton onClick={() => setShowCode(!showCode)}>
          <CodeIcon data-icon="inline-start" />
          {showCode ? "Hide code" : "Edit code"}
        </CornerButton>
        {showCode && (
          <Textarea
            value={code}
            aria-label="Code"
            rows={Math.min(20, Math.max(3, code.split("\n").length))}
            className="mt-2 text-left font-mono text-sm"
            onChange={(e) => set({ code: e.target.value })}
          />
        )}
        <CaptionField
          value={optionOf(options, "fig-cap")}
          onChange={(e) => set({ options: withOption(options, prefix, "fig-cap", e.target.value) })}
        />
      </Controls>
      {props.children}
    </PlateElement>
  );
}

// Figures

const MAX_SVG_BYTES = 200_000;

export function QFigureElement(props: PlateElementProps) {
  const set = useSetNode(props.element);
  const selected = useSelected();
  const { assetUrl, addAsset } = useNotesEditor();
  const file = useRef<HTMLInputElement>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const attrs = props.element.attrs as Attrs;
  const src = props.element.src as string;

  const upload = async (f: File) => {
    const text = await f.text();
    if (f.size > MAX_SVG_BYTES) return setProblem("That SVG is over 200 KB.");
    if (!/^\s*(<\?xml[^>]*>\s*)?(<!--[\s\S]*?-->\s*)*<svg[\s>]/i.test(text)) {
      return setProblem("Choose an SVG file.");
    }
    setProblem(null);
    set({ src: addAsset(f.name, text) });
  };

  return (
    <PlateElement {...props} className="kse-figure">
      <Controls
        className={cn("group/figure relative rounded-lg", selected && "ring-2 ring-ring/30")}
      >
        {src ? (
          <>
            {/* eslint-disable-next-line @next/next/no-img-element -- an SVG of the notes, drawn inert */}
            <img
              src={assetUrl(src)}
              alt={(props.element.caption as string) || ""}
              className="mx-auto max-h-[32rem] max-w-full"
              style={{ width: attr(attrs, "width") }}
            />
            <CornerButton onClick={() => file.current?.click()}>
              <ImageUpIcon data-icon="inline-start" />
              Replace
            </CornerButton>
          </>
        ) : (
          <Button
            variant="outline"
            className="h-24 w-full border-dashed"
            onClick={() => file.current?.click()}
          >
            <ImageUpIcon data-icon="inline-start" />
            Upload an SVG figure
          </Button>
        )}
        {problem && <p className="mt-1 text-sm text-destructive">{problem}</p>}
        <CaptionField
          value={props.element.caption as string}
          onChange={(e) => set({ caption: e.target.value })}
        />
        <input
          ref={file}
          type="file"
          accept=".svg,image/svg+xml"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void upload(f);
            e.target.value = "";
          }}
        />
      </Controls>
      {props.children}
    </PlateElement>
  );
}

export function QCaptionElement(props: PlateElementProps) {
  const set = useSetNode(props.element);
  return (
    <PlateElement {...props} className="group/figure mb-4">
      <Controls>
        <CaptionField
          value={props.element.text as string}
          aria-label="Table caption"
          className="mt-0"
          onChange={(e) => set({ text: e.target.value })}
        />
      </Controls>
      {props.children}
    </PlateElement>
  );
}

export function QRawElement(props: PlateElementProps) {
  const set = useSetNode(props.element);
  const source = props.element.source as string;
  return (
    <PlateElement {...props} className="my-4">
      <Controls>
        <Textarea
          value={source}
          aria-label="Quarto source"
          title="Quarto source the editor shows as written"
          rows={Math.min(20, source.split("\n").length)}
          className="font-mono text-sm"
          onChange={(e) => set({ source: e.target.value })}
        />
      </Controls>
      {props.children}
    </PlateElement>
  );
}

// Inline: citations, cross-references, spans

function RawSource({
  source,
  onChange,
  onDone,
}: {
  source: string;
  onChange: (s: string) => void;
  onDone: () => void;
}) {
  return (
    <Input
      autoFocus
      value={source}
      aria-label="Source"
      className="font-mono text-sm"
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === "Escape") {
          e.preventDefault();
          onDone();
        }
      }}
    />
  );
}

export function QInlineElement(props: PlateElementProps) {
  const set = useSetNode(props.element);
  const selected = useSelected();
  const editor = useEditorRef();
  const { source: notes } = useNotesEditor();
  const [open, setOpen] = useState(false);
  const kind = props.element.kind as InlineKind;
  const source = props.element.source as string;
  const citation = kind === "cite" ? parseCitation(source) : null;
  const done = () => {
    setOpen(false);
    editor.tf.focus();
  };

  // What the published page shows: the reading and page, or "Section 2".
  let label = source;
  if (citation) {
    const items = citation.items.map((i) => {
      const title = notes.references.find((r) => r.id === i.key)?.title ?? i.key;
      return i.locator ? `${title}, ${i.locator}` : title;
    });
    label = citation.bracketed ? `(${items.join("; ")})` : items.join("; ");
  } else if (kind === "xref") {
    label = xrefLabel(editor.children as never, source.replace(/^-?@/, ""));
  }

  return (
    <PlateElement {...props} as="span" className="inline">
      <span contentEditable={false}>
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger
            nativeButton={false}
            render={
              <span
                title={source}
                className={cn(
                  "cursor-pointer rounded-sm transition-colors hover:bg-signal-wash",
                  kind === "cite" || kind === "xref"
                    ? "text-signal"
                    : "font-mono text-[0.875em] text-muted-foreground",
                  selected && "bg-signal-wash",
                )}
              />
            }
          >
            {label}
          </PopoverTrigger>
          <PopoverContent align="start" className={cn(kind === "xref" ? "w-80 p-0" : "w-80")}>
            {citation ? (
              <CitationEditor
                citation={citation}
                onChange={(c) => set({ source: formatCitation(c) })}
              />
            ) : kind === "xref" ? (
              <TargetList
                onPick={(id) => {
                  set({ source: `${source.startsWith("-") ? "-" : ""}@${id}` });
                  done();
                }}
              />
            ) : (
              <RawSource source={source} onChange={(s) => set({ source: s })} onDone={done} />
            )}
          </PopoverContent>
        </Popover>
      </span>
      {props.children}
    </PlateElement>
  );
}

export { empty };
