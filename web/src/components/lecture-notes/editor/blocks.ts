/** New blocks for the insert menu, each written the way the converter reads it back. */

import {
  CodeIcon,
  Columns2Icon,
  GitForkIcon,
  Heading1Icon,
  Heading2Icon,
  Heading3Icon,
  ImageIcon,
  InfoIcon,
  LightbulbIcon,
  ListIcon,
  ListOrderedIcon,
  type LucideIcon,
  MinusIcon,
  PanelRightIcon,
  PilcrowIcon,
  QuoteIcon,
  ScrollTextIcon,
  SigmaIcon,
  SquareChevronDownIcon,
  TableIcon,
  TriangleAlertIcon,
  WorkflowIcon,
  FolderKanbanIcon,
  ChartSplineIcon,
} from "lucide-react";

import { emptyAttrs } from "@/lib/qmd/attrs";
import {
  type CellKind,
  empty,
  QCELL,
  QDETAILS,
  QDIV,
  QFIGURE,
  QTAB,
} from "@/lib/qmd/nodes";

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- Plate nodes are open records.
type Block = Record<string, any>;

const p = (text = ""): Block => ({ type: "p", children: [{ text }] });
const div = (attrs: Partial<ReturnType<typeof emptyAttrs>>, children = [p()]): Block => ({
  type: QDIV,
  attrs: { ...emptyAttrs(), ...attrs },
  children,
});
const shortId = () => Math.random().toString(36).slice(2, 7);

const CELL_SAMPLES: Record<CellKind, string> = {
  dot: "digraph {\n  rankdir=LR\n  A -> B\n}",
  mermaid: "flowchart LR\n  A --> B",
  ojs: "viewof k = Inputs.range([0, 10], {step: 1, label: \"k\"})",
};
const cell = (kind: CellKind): Block => ({
  type: QCELL,
  kind,
  options: [],
  code: CELL_SAMPLES[kind],
  children: empty(),
});

export type InsertItem = {
  key: string;
  label: string;
  group: "Text" | "Lists" | "Math & code" | "Callouts" | "Theorems" | "Diagrams" | "Layout";
  icon: LucideIcon;
  /** More words the search matches. */
  keywords?: string;
  make: () => Block | Block[];
};

const callout = (kind: string, label: string, icon: LucideIcon): InsertItem => ({
  key: `callout-${kind}`,
  label,
  group: "Callouts",
  icon,
  keywords: "callout box",
  make: () => div({ classes: [`callout-${kind}`] }),
});

const theorem = (prefix: string, label: string): InsertItem => ({
  key: `theorem-${prefix}`,
  label,
  group: "Theorems",
  icon: ScrollTextIcon,
  keywords: "theorem definition lemma",
  // The first heading inside is the block's name.
  make: () =>
    div({ id: `${prefix}${shortId()}` }, [{ type: "h2", children: [{ text: "Name" }] }, p()]),
});

export const INSERT_ITEMS: InsertItem[] = [
  { key: "p", label: "Text", group: "Text", icon: PilcrowIcon, keywords: "paragraph", make: () => p() },
  { key: "h2", label: "Heading", group: "Text", icon: Heading1Icon, keywords: "h2 section", make: () => ({ type: "h2", children: [{ text: "" }] }) },
  { key: "h3", label: "Subheading", group: "Text", icon: Heading2Icon, keywords: "h3", make: () => ({ type: "h3", children: [{ text: "" }] }) },
  { key: "h4", label: "Small heading", group: "Text", icon: Heading3Icon, keywords: "h4", make: () => ({ type: "h4", children: [{ text: "" }] }) },
  { key: "blockquote", label: "Quote", group: "Text", icon: QuoteIcon, make: () => ({ type: "blockquote", children: [p()] }) },
  { key: "hr", label: "Divider", group: "Text", icon: MinusIcon, keywords: "rule line", make: () => [{ type: "hr", children: [{ text: "" }] }, p()] },

  { key: "ul", label: "Bulleted list", group: "Lists", icon: ListIcon, make: () => ({ ...p(), indent: 1, listStyleType: "disc" }) },
  { key: "ol", label: "Numbered list", group: "Lists", icon: ListOrderedIcon, make: () => ({ ...p(), indent: 1, listStyleType: "decimal" }) },

  { key: "equation", label: "Equation", group: "Math & code", icon: SigmaIcon, keywords: "math tex latex formula", make: () => ({ type: "equation", texExpression: "", children: empty() }) },
  { key: "code", label: "Code", group: "Math & code", icon: CodeIcon, make: () => ({ type: "code_block", lang: "python", children: [{ type: "code_line", children: [{ text: "" }] }] }) },
  {
    key: "table",
    label: "Table",
    group: "Math & code",
    icon: TableIcon,
    make: () => {
      const row = (type: string) => ({ type: "tr", children: [0, 1, 2].map(() => ({ type, children: [p()] })) });
      return { type: "table", children: [row("th"), row("td"), row("td")] };
    },
  },

  callout("note", "Note", InfoIcon),
  callout("tip", "Tip", LightbulbIcon),
  callout("important", "Important", InfoIcon),
  callout("warning", "Warning", TriangleAlertIcon),
  callout("caution", "Caution", TriangleAlertIcon),
  {
    key: "learning-goals",
    label: "Learning goals",
    group: "Callouts",
    icon: LightbulbIcon,
    make: () =>
      div({ classes: ["callout-note", "learning-goals"], kv: [["title", "What you will learn"]] }, [
        { ...p(), indent: 1, listStyleType: "disc" },
      ]),
  },
  {
    key: "collapsed",
    label: "Collapsed solution",
    group: "Callouts",
    icon: SquareChevronDownIcon,
    keywords: "answer proof derivation hide",
    make: () => div({ classes: ["callout-note"], kv: [["collapse", "true"], ["title", "Solution"]] }),
  },

  {
    key: "proof",
    label: "Proof",
    group: "Theorems",
    icon: SquareChevronDownIcon,
    keywords: "proof derivation collapsed",
    // The skill's convention: a collapsed note titled "Proof" right after the theorem.
    make: () => div({ classes: ["callout-note"], kv: [["collapse", "true"], ["title", "Proof"]] }),
  },
  theorem("def-", "Definition"),
  theorem("thm-", "Theorem"),
  theorem("lem-", "Lemma"),
  theorem("cor-", "Corollary"),
  theorem("prp-", "Proposition"),
  theorem("exm-", "Example"),
  theorem("exr-", "Exercise"),

  {
    key: "figure",
    label: "Figure (SVG)",
    group: "Diagrams",
    icon: ImageIcon,
    keywords: "image picture svg upload",
    make: () => ({ type: QFIGURE, src: "", caption: "", attrs: emptyAttrs(), children: empty() }),
  },
  { key: "dot", label: "Graphviz diagram", group: "Diagrams", icon: GitForkIcon, keywords: "graph dot", make: () => cell("dot") },
  { key: "mermaid", label: "Mermaid diagram", group: "Diagrams", icon: WorkflowIcon, keywords: "flowchart sequence", make: () => cell("mermaid") },
  { key: "ojs", label: "Interactive (OJS)", group: "Diagrams", icon: ChartSplineIcon, keywords: "observable slider plot", make: () => cell("ojs") },

  {
    key: "tabs",
    label: "Tabs",
    group: "Layout",
    icon: FolderKanbanIcon,
    keywords: "tabset panel",
    make: () =>
      div({ classes: ["panel-tabset"] }, [
        { type: QTAB, title: "First", level: 2, children: [p()] },
        { type: QTAB, title: "Second", level: 2, children: [p()] },
      ]),
  },
  {
    key: "columns",
    label: "Two columns",
    group: "Layout",
    icon: Columns2Icon,
    make: () =>
      div({ classes: ["columns"] }, [
        div({ classes: ["column"], kv: [["width", "50%"]] }),
        div({ classes: ["column"], kv: [["width", "50%"]] }),
      ]),
  },
  { key: "margin", label: "Margin note", group: "Layout", icon: PanelRightIcon, keywords: "aside side", make: () => div({ classes: ["column-margin"] }) },
  {
    key: "details",
    label: "Details",
    group: "Layout",
    icon: SquareChevronDownIcon,
    keywords: "toggle collapse summary",
    make: () => ({ type: QDETAILS, summary: "Details", children: [p()] }),
  },
];
