"use client";

import { useRef, useState } from "react";
import { FileTextIcon, PlusIcon, UploadIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemGroup,
  ItemMedia,
  ItemTitle,
} from "@/components/ui/item";
import { Separator } from "@/components/ui/separator";
import {
  ApiError,
  attachFile,
  fileName,
  uploadFiles,
  type PlanView,
  type SavedFile,
  type SessionView,
} from "@/lib/api";

type AddMaterialDialogProps = {
  course: string;
  courseId?: number;
  entry: SessionView;
  readingFiles: SavedFile[];
  onPlan: (plan: PlanView) => void;
  onUploaded: () => void;
};

export function AddMaterialDialog({
  course,
  courseId,
  entry,
  readingFiles,
  onPlan,
  onUploaded,
}: AddMaterialDialogProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const attached = new Set(entry.files.map((file) => file.path));
  const available = readingFiles.filter((file) => !attached.has(file.path));

  const attachAll = async (paths: string[]) => {
    let plan: PlanView | null = null;
    for (const path of paths) plan = await attachFile(course, entry.id, path);
    if (plan) onPlan(plan);
  };

  const run = async (action: () => Promise<void>) => {
    setPending(true);
    setError(null);
    try {
      await action();
      setOpen(false);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't reach the server. Please try again.",
      );
    } finally {
      setPending(false);
    }
  };

  const onUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (picked.length === 0) return;
    run(async () => {
      const saved = await uploadFiles("reading", picked, courseId);
      onUploaded();
      await attachAll(saved.map((file) => file.path));
    });
  };

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        className="self-start"
        onClick={() => {
          setError(null);
          setOpen(true);
        }}
      >
        <PlusIcon />
        Add material
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add material to {entry.session.label}</DialogTitle>
            <DialogDescription>
              Upload a new file or pick one already uploaded for this course.
            </DialogDescription>
          </DialogHeader>

          <input ref={inputRef} type="file" multiple onChange={onUpload} className="hidden" />
          <Button disabled={pending} onClick={() => inputRef.current?.click()}>
            <UploadIcon />
            {pending ? "Saving…" : "Upload file"}
          </Button>

          <Separator />

          <span className="text-sm font-medium">Choose existing</span>
          {available.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No other reading materials uploaded for this course.
            </p>
          ) : (
            <ItemGroup className="max-h-72 gap-2 overflow-y-auto">
              {available.map((file) => (
                <Item key={file.path} variant="outline" size="sm">
                  <ItemMedia variant="icon">
                    <FileTextIcon />
                  </ItemMedia>
                  <ItemContent className="min-w-0">
                    <ItemTitle className="block w-full truncate" title={fileName(file.path)}>
                      {fileName(file.path)}
                    </ItemTitle>
                  </ItemContent>
                  <ItemActions>
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={pending}
                      onClick={() => run(() => attachAll([file.path]))}
                    >
                      Add
                    </Button>
                  </ItemActions>
                </Item>
              ))}
            </ItemGroup>
          )}

          {error && <p className="text-sm text-destructive">{error}</p>}
        </DialogContent>
      </Dialog>
    </>
  );
}
