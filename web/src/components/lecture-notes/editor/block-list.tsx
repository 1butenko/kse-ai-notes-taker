"use client";

/** Numbered list items: Plate's lists are flat paragraphs with `listStyleType`; bulleted ones
 * are drawn by the list plugin's injected `display: list-item`, numbered ones need an <ol>. */

import { isOrderedList } from "@platejs/list";
import type { TListElement } from "platejs";
import type { PlateElementProps, RenderNodeWrapper } from "platejs/react";

export const BlockList: RenderNodeWrapper = (props) => {
  if (!props.element.listStyleType) return;
  return function List(props: PlateElementProps) {
    const { listStart, listStyleType } = props.element as TListElement;
    const Tag = isOrderedList(props.element) ? "ol" : "ul";
    return (
      <Tag className="relative m-0 p-0" style={{ listStyleType }} start={listStart}>
        <li>{props.children}</li>
      </Tag>
    );
  };
};
