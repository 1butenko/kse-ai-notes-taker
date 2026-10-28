"use client";

import { useRef, type ReactNode } from "react";
import { ExternalLinkIcon, EyeIcon, FileTextIcon, UploadIcon, XIcon } from "lucide-react";

import { useFileViewer } from "@/components/dashboard/file-viewer";

import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Empty,
  EmptyContent,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemMedia,
  ItemTitle,
} from "@/components/ui/item";
import { fileName, type SavedFile } from "@/lib/api";
import { formatSize } from "@/lib/format";
import type { MoodleFile } from "@/lib/moodle-files";

type FileUploadCardProps = {
  title: string;
  icon: ReactNode;
  emptyTitle: string;
  accept: string;
  multiple?: boolean;
  files: File[];
  onFilesChange: (files: File[]) => void;
  moodleFiles?: MoodleFile[];
  onRemoveMoodleFile?: (id: string) => void;
  savedFiles?: SavedFile[];
  actions?: ReactNode;
};

export function FileUploadCard({
  title,
  icon,
  emptyTitle,
  accept,
  multiple = false,
  files,
  onFilesChange,
  moodleFiles = [],
  onRemoveMoodleFile,
  savedFiles = [],
  actions,
}: FileUploadCardProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const openFile = useFileViewer();

  const isEmpty = files.length === 0 && moodleFiles.length === 0 && savedFiles.length === 0;

  const openPicker = () => inputRef.current?.click();

  const onChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(event.target.files ?? []);
    onFilesChange(multiple ? [...files, ...picked] : picked.slice(0, 1));
    event.target.value = "";
  };

  const remove = (index: number) => onFilesChange(files.filter((_, i) => i !== index));

  return (
    <Card className="gap-3 overflow-visible bg-transparent py-0 ring-0 [--card-spacing:0px]">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {(!isEmpty || actions) && (
          <CardAction className="flex gap-2">
            {actions}
            {!isEmpty && (
              <Button variant="outline" size="sm" onClick={openPicker}>
                <UploadIcon />
                {multiple ? "Add more" : files.length > 0 ? "Replace" : "Upload"}
              </Button>
            )}
          </CardAction>
        )}
      </CardHeader>

      <CardContent>
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          multiple={multiple}
          onChange={onChange}
          className="hidden"
        />

        {isEmpty ? (
          <Empty className="border border-dashed">
            <EmptyHeader>
              <EmptyMedia variant="icon">{icon}</EmptyMedia>
              <EmptyTitle>{emptyTitle}</EmptyTitle>
            </EmptyHeader>
            <EmptyContent>
              <Button variant="outline" onClick={openPicker}>
                <UploadIcon />
                {multiple ? "Upload files" : "Upload file"}
              </Button>
            </EmptyContent>
          </Empty>
        ) : (
          <ItemGroup className="gap-2">
            {savedFiles.map((file) => (
              <Item key={file.path} variant="outline">
                <ItemMedia variant="icon">
                  <FileTextIcon />
                </ItemMedia>
                <ItemContent className="min-w-0">
                  <ItemTitle className="block w-full truncate" title={fileName(file.path)}>
                    {fileName(file.path)}
                  </ItemTitle>
                  <ItemDescription>{formatSize(file.size)}</ItemDescription>
                </ItemContent>
                <ItemActions>
                  <Badge variant="outline">Saved</Badge>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Open ${fileName(file.path)}`}
                    onClick={() => openFile({ path: file.path })}
                  >
                    <EyeIcon />
                  </Button>
                </ItemActions>
              </Item>
            ))}
            {moodleFiles.map((file) => (
              <Item key={file.id} variant="outline">
                <ItemMedia variant="icon">
                  <FileTextIcon />
                </ItemMedia>
                <ItemContent className="min-w-0">
                  <ItemTitle className="block w-full truncate" title={file.name}>
                    {file.name}
                  </ItemTitle>
                  <ItemDescription className="truncate" title={file.filename}>
                    {file.filename}
                    {file.size > 0 && ` · ${formatSize(file.size)}`}
                  </ItemDescription>
                </ItemContent>
                <ItemActions>
                  <Badge variant="secondary">Moodle</Badge>
                  <a
                    href={file.url}
                    target="_blank"
                    rel="noreferrer"
                    aria-label={`Open ${file.name} in Moodle`}
                    className={buttonVariants({ variant: "ghost", size: "icon-sm" })}
                  >
                    <ExternalLinkIcon />
                  </a>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Remove ${file.name}`}
                    onClick={() => onRemoveMoodleFile?.(file.id)}
                  >
                    <XIcon />
                  </Button>
                </ItemActions>
              </Item>
            ))}
            {files.map((file, index) => (
              <Item key={`${file.name}-${index}`} variant="outline">
                <ItemMedia variant="icon">
                  <FileTextIcon />
                </ItemMedia>
                <ItemContent className="min-w-0">
                  <ItemTitle className="block w-full truncate" title={file.name}>
                    {file.name}
                  </ItemTitle>
                  <ItemDescription>{formatSize(file.size)}</ItemDescription>
                </ItemContent>
                <ItemActions>
                  <Badge variant="secondary">Attached</Badge>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Remove ${file.name}`}
                    onClick={() => remove(index)}
                  >
                    <XIcon />
                  </Button>
                </ItemActions>
              </Item>
            ))}
          </ItemGroup>
        )}
      </CardContent>
    </Card>
  );
}
