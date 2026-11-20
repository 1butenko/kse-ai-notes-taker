"use client";

/** The gutter left of each top-level block, as in Notion: "+" opens the insert menu and the
 * grip drags the block (click it for the block's actions). */

import { useDraggable, useDropLine } from "@platejs/dnd";
import { CopyIcon, GripVerticalIcon, PlusIcon, Trash2Icon } from "lucide-react";
import {
  MemoizedChildren,
  type PlateElementProps,
  type RenderNodeWrapper,
  useEditorRef,
} from "platejs/react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

import { useNotesEditor } from "./context";

export const BlockDraggable: RenderNodeWrapper = ({ editor, path }) => {
  if (editor.dom.readOnly || path.length !== 1) return;
  return function Wrapped(props: PlateElementProps) {
    return <Draggable {...props} />;
  };
};

function Draggable({ children, element }: PlateElementProps) {
  const editor = useEditorRef();
  const { openInsertMenu } = useNotesEditor();
  const { isDragging, nodeRef, handleRef } = useDraggable({ element });
  const path = () => editor.api.findPath(element)!;

  return (
    <div className={cn("group/block relative", isDragging && "opacity-50")}>
      <div
        contentEditable={false}
        className="absolute top-1 -left-14 flex opacity-0 transition-opacity group-hover/block:opacity-100 focus-within:opacity-100"
      >
        <Button
          variant="ghost"
          size="icon-xs"
          aria-label="Insert a block"
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => openInsertMenu(path())}
        >
          <PlusIcon />
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                ref={handleRef}
                variant="ghost"
                size="icon-xs"
                aria-label="Drag to move, click for actions"
                className="cursor-grab"
              />
            }
          >
            <GripVerticalIcon />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-44">
            <DropdownMenuGroup>
              <DropdownMenuItem
                onClick={() => {
                  const { id: _id, ...copy } = element;
                  void _id;
                  editor.tf.insertNodes(structuredClone(copy), { at: [path()[0] + 1] });
                }}
              >
                <CopyIcon />
                Duplicate
              </DropdownMenuItem>
              <DropdownMenuItem
                variant="destructive"
                onClick={() => editor.tf.removeNodes({ at: path() })}
              >
                <Trash2Icon />
                Delete
              </DropdownMenuItem>
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <div ref={nodeRef}>
        <MemoizedChildren>{children}</MemoizedChildren>
        <DropLine />
      </div>
    </div>
  );
}

function DropLine() {
  const { dropLine } = useDropLine();
  if (!dropLine) return null;
  return (
    <div
      contentEditable={false}
      className={cn(
        "absolute inset-x-0 h-0.5 bg-primary/60",
        dropLine === "top" ? "-top-px" : "-bottom-px",
      )}
    />
  );
}
