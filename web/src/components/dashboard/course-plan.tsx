"use client";

import { EyeIcon, FileTextIcon, ScissorsIcon, XIcon } from "lucide-react";

import { useFileViewer } from "@/components/dashboard/file-viewer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemMedia,
  ItemTitle,
} from "@/components/ui/item";
import { fileName, type FileView } from "@/lib/api";
import { cn } from "@/lib/utils";

export function FileRow({
  file,
  label,
  onRemove,
}: {
  file: FileView;
  label: string;
  onRemove: () => void;
}) {
  const openFile = useFileViewer();
  const excerpt = file.excerpt;
  const name = excerpt ? excerpt.label : fileName(file.path);
  return (
    <Item
      variant="outline"
      size="sm"
      className={cn(excerpt && "border-success/50 bg-success/5")}
    >
      <ItemMedia variant="icon" className={cn(excerpt && "text-success")}>
        {excerpt ? <ScissorsIcon /> : <FileTextIcon />}
      </ItemMedia>
      <ItemContent className="min-w-0">
        <ItemTitle className="block w-full truncate" title={name}>
          {name}
        </ItemTitle>
        {excerpt && (
          <ItemDescription className="truncate">
            {excerpt.printed ?? `PDF pp. ${excerpt.pdf_start}–${excerpt.pdf_end}`} of{" "}
            {fileName(excerpt.book)}
          </ItemDescription>
        )}
      </ItemContent>
      <ItemActions>
        {excerpt && <Badge className="bg-success/15 text-success">Cropped</Badge>}
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={`Open ${name}`}
          onClick={() => openFile({ path: file.path, title: name })}
        >
          <EyeIcon />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={`${excerpt ? "Delete" : label} ${name}`}
          onClick={onRemove}
        >
          <XIcon />
        </Button>
      </ItemActions>
    </Item>
  );
}
