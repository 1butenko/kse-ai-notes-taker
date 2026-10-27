"use client";

import { useRef, useState } from "react";
import { CheckIcon, EyeIcon, FileTextIcon, PlusIcon, ScissorsIcon, UploadIcon } from "lucide-react";

import { useFileViewer } from "@/components/dashboard/file-viewer";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
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
  addExcerpt,
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

const isPdf = (path: string) => /\.pdf$/i.test(path);

export function AddMaterialDialog({
  course,
  courseId,
  entry,
  readingFiles,
  onPlan,
  onUploaded,
}: AddMaterialDialogProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const openFile = useFileViewer();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cropping, setCropping] = useState<string | null>(null);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  const attached = new Set(entry.files.map((file) => file.path));
  const pages = { pdf_start: Number(start), pdf_end: Number(end) };
  const validPages =
    Number.isInteger(pages.pdf_start) &&
    Number.isInteger(pages.pdf_end) &&
    pages.pdf_start >= 1 &&
    pages.pdf_start <= pages.pdf_end;

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

  const toggleCrop = (path: string) => {
    setError(null);
    setStart("");
    setEnd("");
    setCropping(cropping === path ? null : path);
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
          setCropping(null);
          setOpen(true);
        }}
      >
        <PlusIcon />
        Add material
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>Add material to {entry.session.label}</DialogTitle>
            <DialogDescription>
              Upload a new file, or add a whole file or a page range from one already uploaded.
            </DialogDescription>
          </DialogHeader>

          <input ref={inputRef} type="file" multiple onChange={onUpload} className="hidden" />
          <Button disabled={pending} onClick={() => inputRef.current?.click()}>
            <UploadIcon />
            {pending ? "Saving…" : "Upload file"}
          </Button>

          <Separator />

          <span className="text-sm font-medium">Choose existing</span>
          {readingFiles.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No reading materials uploaded for this course.
            </p>
          ) : (
            <ItemGroup className="max-h-80 gap-2 overflow-y-auto">
              {readingFiles.map((file) => {
                const name = fileName(file.path);
                const pdf = isPdf(file.path);
                const isAttached = attached.has(file.path);
                return (
                  <div key={file.path} className="flex flex-col gap-2">
                    <Item variant="outline" size="sm">
                      <ItemMedia variant="icon">
                        <FileTextIcon />
                      </ItemMedia>
                      <ItemContent className="min-w-0">
                        <ItemTitle className="block w-full truncate" title={name}>
                          {name}
                        </ItemTitle>
                      </ItemContent>
                      <ItemActions>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`Open ${name}`}
                          onClick={() => openFile({ path: file.path })}
                        >
                          <EyeIcon />
                        </Button>
                        {pdf && (
                          <Button
                            size="sm"
                            variant={cropping === file.path ? "secondary" : "ghost"}
                            disabled={pending}
                            onClick={() => toggleCrop(file.path)}
                          >
                            <ScissorsIcon />
                            Pages
                          </Button>
                        )}
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={pending || isAttached}
                          onClick={() => run(() => attachAll([file.path]))}
                        >
                          {isAttached && <CheckIcon />}
                          {isAttached ? "Added" : "Add"}
                        </Button>
                      </ItemActions>
                    </Item>
                    {cropping === file.path && (
                      <div className="flex flex-wrap items-center gap-2 pl-3">
                        <span className="text-xs text-muted-foreground">PDF pages</span>
                        <Input
                          aria-label="First PDF page"
                          inputMode="numeric"
                          className="h-8 w-20"
                          autoFocus
                          value={start}
                          onChange={(event) => setStart(event.target.value)}
                        />
                        <span>to</span>
                        <Input
                          aria-label="Last PDF page"
                          inputMode="numeric"
                          className="h-8 w-20"
                          value={end}
                          onChange={(event) => setEnd(event.target.value)}
                        />
                        <Button
                          size="sm"
                          disabled={pending || !validPages}
                          onClick={() =>
                            run(async () =>
                              onPlan(await addExcerpt(course, entry.id, file.path, pages)),
                            )
                          }
                        >
                          <ScissorsIcon />
                          Add pages
                        </Button>
                      </div>
                    )}
                  </div>
                );
              })}
            </ItemGroup>
          )}

          {error && <p className="text-sm text-destructive">{error}</p>}
        </DialogContent>
      </Dialog>
    </>
  );
}
