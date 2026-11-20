"use client";

/** Plate's Markdown nodes in the editor. They draw plain elements; `notes-editor.css` gives them
 * the published page's look. */

import { PlateElement, type PlateElementProps } from "platejs/react";

import { HEADING_ATTRS } from "@/lib/qmd/nodes";
import type { Attrs } from "@/lib/qmd/attrs";
import { cn } from "@/lib/utils";

export function ParagraphElement(props: PlateElementProps) {
  return (
    <PlateElement {...props} className="kse-p">
      {props.children}
    </PlateElement>
  );
}

export function HeadingElement(props: PlateElementProps) {
  const type = props.element.type as "h1" | "h2" | "h3" | "h4" | "h5" | "h6";
  const attrs = props.element[HEADING_ATTRS] as Attrs | undefined;
  // Sections are top-level headings, numbered as on the published page; a heading inside a
  // theorem or tab is its name.
  const section = props.path.length === 1 && type !== "h1";
  return (
    <PlateElement
      {...props}
      as={type}
      className={cn(section && "kse-section", attrs?.classes.includes("unnumbered") && "unnumbered")}
    >
      {props.children}
    </PlateElement>
  );
}

export function BlockquoteElement(props: PlateElementProps) {
  return (
    <PlateElement {...props} as="blockquote">
      {props.children}
    </PlateElement>
  );
}

export function HrElement(props: PlateElementProps) {
  return (
    <PlateElement {...props}>
      <div contentEditable={false}>
        <hr />
      </div>
      {props.children}
    </PlateElement>
  );
}

export function CodeBlockElement(props: PlateElementProps) {
  return (
    <PlateElement {...props} as="pre">
      <code>{props.children}</code>
    </PlateElement>
  );
}

export function CodeLineElement(props: PlateElementProps) {
  return <PlateElement {...props}>{props.children}</PlateElement>;
}

export function TableElement(props: PlateElementProps) {
  return (
    <PlateElement {...props} className="overflow-x-auto">
      <table>
        <tbody>{props.children}</tbody>
      </table>
    </PlateElement>
  );
}

export function TableRowElement(props: PlateElementProps) {
  return (
    <PlateElement {...props} as="tr">
      {props.children}
    </PlateElement>
  );
}

export function TableCellElement(props: PlateElementProps) {
  return (
    <PlateElement {...props} as="td">
      {props.children}
    </PlateElement>
  );
}

export function TableCellHeaderElement(props: PlateElementProps) {
  return (
    <PlateElement {...props} as="th">
      {props.children}
    </PlateElement>
  );
}

export function LinkElement(props: PlateElementProps) {
  return (
    <PlateElement
      {...props}
      as="a"
      attributes={{
        ...props.attributes,
        href: props.element.url as string,
        title: props.element.url as string,
      }}
    >
      {props.children}
    </PlateElement>
  );
}
