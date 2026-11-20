"use client";

/** The editor's plugins: Plate's own for Markdown, ours for the Quarto-only nodes in
 * `@/lib/qmd/nodes`. Node keys match the headless editor the converter uses. */

import {
  BlockquoteRules,
  BoldRules,
  CodeRules,
  HeadingRules,
  HorizontalRuleRules,
  ItalicRules,
  StrikethroughRules,
} from "@platejs/basic-nodes";
import {
  BlockquotePlugin,
  BoldPlugin,
  CodePlugin,
  H1Plugin,
  H2Plugin,
  H3Plugin,
  H4Plugin,
  H5Plugin,
  H6Plugin,
  HorizontalRulePlugin,
  ItalicPlugin,
  StrikethroughPlugin,
  SubscriptPlugin,
  SuperscriptPlugin,
  UnderlinePlugin,
} from "@platejs/basic-nodes/react";
import { CodeBlockRules } from "@platejs/code-block";
import { CodeBlockPlugin, CodeLinePlugin } from "@platejs/code-block/react";
import { DndPlugin } from "@platejs/dnd";
import { IndentPlugin } from "@platejs/indent/react";
import { LinkPlugin } from "@platejs/link/react";
import { BulletedListRules, OrderedListRules } from "@platejs/list";
import { ListPlugin } from "@platejs/list/react";
import { MathRules } from "@platejs/math";
import { EquationPlugin, InlineEquationPlugin } from "@platejs/math/react";
import {
  TableCellHeaderPlugin,
  TableCellPlugin,
  TablePlugin,
  TableRowPlugin,
} from "@platejs/table/react";
import { KEYS, TrailingBlockPlugin } from "platejs";
import { createPlatePlugin, ParagraphPlugin } from "platejs/react";
import { DndProvider } from "react-dnd";
import { HTML5Backend } from "react-dnd-html5-backend";

import { markdownPlugin } from "@/lib/qmd/markdown-editor";
import {
  QCAPTION,
  QCELL,
  QDETAILS,
  QDIV,
  QFIGURE,
  QINLINE,
  QRAW,
  QTAB,
} from "@/lib/qmd/nodes";

import { BlockDraggable } from "./block-draggable";
import { BlockList } from "./block-list";
import {
  BlockquoteElement,
  CodeBlockElement,
  CodeLineElement,
  HeadingElement,
  HrElement,
  LinkElement,
  ParagraphElement,
  TableCellElement,
  TableCellHeaderElement,
  TableElement,
  TableRowElement,
} from "./markdown-nodes";
import { EquationElement, InlineEquationElement } from "./equation-nodes";
import {
  QCaptionElement,
  QCellElement,
  QDetailsElement,
  QDivElement,
  QFigureElement,
  QInlineElement,
  QRawElement,
  QTabElement,
} from "./quarto-nodes";

const element = (key: string, component: React.FC<never>, extra = {}) =>
  createPlatePlugin({
    key,
    node: { isElement: true, component: component as never, ...extra },
  });

const LIST_TARGETS = [...KEYS.heading, KEYS.p, KEYS.blockquote, KEYS.codeBlock];

export const editorPlugins = [
  // Blocks
  ParagraphPlugin.withComponent(ParagraphElement),
  H1Plugin.configure({ node: { component: HeadingElement } }),
  H2Plugin.configure({ node: { component: HeadingElement } }),
  H3Plugin.configure({ node: { component: HeadingElement } }),
  H4Plugin.configure({ node: { component: HeadingElement } }),
  H5Plugin.configure({ node: { component: HeadingElement } }),
  H6Plugin.configure({ node: { component: HeadingElement } }),
  BlockquotePlugin.configure({
    node: { component: BlockquoteElement },
    inputRules: [BlockquoteRules.markdown()],
  }),
  HorizontalRulePlugin.configure({
    node: { component: HrElement },
    inputRules: [HorizontalRuleRules.markdown({ variant: "-" })],
  }),
  createPlatePlugin({
    key: "headingRules",
    inputRules: [HeadingRules.markdown()],
  }),
  CodeBlockPlugin.configure({
    node: { component: CodeBlockElement },
    inputRules: [CodeBlockRules.markdown({ on: "match" })],
  }),
  CodeLinePlugin.withComponent(CodeLineElement),
  TablePlugin.withComponent(TableElement),
  TableRowPlugin.withComponent(TableRowElement),
  TableCellPlugin.withComponent(TableCellElement),
  TableCellHeaderPlugin.withComponent(TableCellHeaderElement),
  LinkPlugin.withComponent(LinkElement),
  IndentPlugin.configure({
    inject: { targetPlugins: LIST_TARGETS },
    options: { offset: 24 },
  }),
  ListPlugin.configure({
    inputRules: [
      BulletedListRules.markdown({ variant: "-" }),
      BulletedListRules.markdown({ variant: "*" }),
      OrderedListRules.markdown({ variant: "." }),
    ],
    inject: { targetPlugins: LIST_TARGETS },
    render: { belowNodes: BlockList },
  }),

  // Math
  InlineEquationPlugin.configure({
    node: { component: InlineEquationElement },
    inputRules: [MathRules.markdown({ variant: "$" })],
  }),
  EquationPlugin.configure({
    node: { component: EquationElement },
    inputRules: [MathRules.markdown({ on: "break", variant: "$$" })],
  }),

  // Marks
  BoldPlugin.configure({ inputRules: [BoldRules.markdown({ variant: "*" })] }),
  ItalicPlugin.configure({
    inputRules: [ItalicRules.markdown({ variant: "_" }), ItalicRules.markdown({ variant: "*" })],
  }),
  UnderlinePlugin,
  StrikethroughPlugin.configure({ inputRules: [StrikethroughRules.markdown()] }),
  CodePlugin.configure({ inputRules: [CodeRules.markdown()] }),
  SubscriptPlugin,
  SuperscriptPlugin,

  // Quarto
  element(QDIV, QDivElement, { isContainer: true }),
  element(QTAB, QTabElement, { isContainer: true }),
  element(QDETAILS, QDetailsElement, { isContainer: true }),
  element(QCELL, QCellElement, { isVoid: true }),
  element(QFIGURE, QFigureElement, { isVoid: true }),
  element(QCAPTION, QCaptionElement, { isVoid: true }),
  element(QRAW, QRawElement, { isVoid: true }),
  element(QINLINE, QInlineElement, { isVoid: true, isInline: true }),

  // Drag handles on top-level blocks
  DndPlugin.configure({
    render: {
      aboveNodes: BlockDraggable,
      aboveSlate: ({ children }) => <DndProvider backend={HTML5Backend}>{children}</DndProvider>,
    },
  }),

  // An empty paragraph always ends the page, to type below the last block.
  TrailingBlockPlugin,

  markdownPlugin,
];
