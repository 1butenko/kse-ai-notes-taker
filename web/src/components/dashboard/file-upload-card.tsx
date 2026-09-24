"use client";

import { useRef, useState, type ReactNode } from "react";
import { FileTextIcon, UploadIcon, XIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
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

type FileUploadCardProps = {
  title: string;
  description: string;
  icon: ReactNode;
  emptyTitle: string;
  emptyDescription: string;
  accept: string;
  multiple?: boolean;
};

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function FileUploadCard({
  title,
  description,
  icon,
  emptyTitle,
  emptyDescription,
  accept,
  multiple = false,
}: FileUploadCardProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);

  const openPicker = () => inputRef.current?.click();

  const onChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(event.target.files ?? []);
    setFiles((prev) => (multiple ? [...prev, ...picked] : picked.slice(0, 1)));
    event.target.value = "";
  };

  const remove = (index: number) =>
    setFiles((prev) => prev.filter((_, i) => i !== index));

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
        {files.length > 0 && (
          <CardAction>
            <Button variant="outline" size="sm" onClick={openPicker}>
              <UploadIcon />
              {multiple ? "Add more" : "Replace"}
            </Button>
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

        {files.length === 0 ? (
          <Empty className="border border-dashed">
            <EmptyHeader>
              <EmptyMedia variant="icon">{icon}</EmptyMedia>
              <EmptyTitle>{emptyTitle}</EmptyTitle>
              <EmptyDescription>{emptyDescription}</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
              <Button onClick={openPicker}>
                <UploadIcon />
                {multiple ? "Upload files" : "Upload file"}
              </Button>
            </EmptyContent>
          </Empty>
        ) : (
          <ItemGroup className="gap-2">
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
                  <Badge variant="secondary">Uploaded</Badge>
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
