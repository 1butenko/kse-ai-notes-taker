"use client";

import { useRef, useState } from "react";
import { BookOpenIcon, EyeIcon, InboxIcon, UploadIcon } from "lucide-react";
import { toast } from "sonner";

import { autoMatch } from "@/components/course/auto-match";
import { FileRow } from "@/components/dashboard/course-plan";
import { useFileViewer } from "@/components/dashboard/file-viewer";
import { BooksPanel } from "@/components/dashboard/mapping-parts";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ItemGroup } from "@/components/ui/item";
import { Spinner } from "@/components/ui/spinner";
import {
  ApiError,
  dismissUnassigned,
  fileName,
  uploadFiles,
  type PlanView,
  type SavedFile,
} from "@/lib/api";
import { formatSize } from "@/lib/format";

type MaterialsPanelProps = {
  plan: PlanView;
  courseId?: number;
  readingFiles: SavedFile[];
  onPlan: (plan: PlanView) => void;
  onUploaded: () => void;
};

function errorMessage(err: unknown) {
  return err instanceof ApiError ? err.message : "Couldn't reach the server.";
}

/** How many lectures read from this file, whole or as an excerpt. */
function lecturesUsing(plan: PlanView, path: string) {
  return plan.sessions.filter((s) =>
    s.files.some((f) => f.path === path || f.excerpt?.book === path),
  ).length;
}

export function MaterialsPanel({
  plan,
  courseId,
  readingFiles,
  onPlan,
  onUploaded,
}: MaterialsPanelProps) {
  const openFile = useFileViewer();
  const inputRef = useRef<HTMLInputElement>(null);
  const [step, setStep] = useState<"idle" | "uploading" | "matching">("idle");
  const [booksOpen, setBooksOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const update = async (action: () => Promise<PlanView>) => {
    if (busy) return;
    setBusy(true);
    try {
      onPlan(await action());
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  // A new reading is matched to the lectures straight away; earlier decisions stay.
  const add = async (files: File[]) => {
    if (files.length === 0) return;
    setStep("uploading");
    try {
      await uploadFiles("reading", files, courseId);
      onUploaded();
      setStep("matching");
      onPlan(await autoMatch(plan.course));
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setStep("idle");
    }
  };

  return (
    <aside
      aria-labelledby="materials-title"
      className="flex min-w-0 flex-col gap-4 rounded-xl bg-muted p-4 lg:sticky lg:top-4"
    >
      <div className="flex items-center justify-between gap-2">
        <h2 id="materials-title" className="text-base">
          Readings
        </h2>
        <span className="text-sm text-muted-foreground tabular-nums">{readingFiles.length}</span>
      </div>

      {readingFiles.length > 0 ? (
        <ul className="flex flex-col">
          {readingFiles.map((file) => {
            const uses = lecturesUsing(plan, file.path);
            const name = fileName(file.path);
            return (
              <li key={file.path} className="border-b border-border last:border-b-0">
                <button
                  type="button"
                  onClick={() => openFile({ path: file.path })}
                  className="group flex w-full items-start gap-2 py-2.5 text-left"
                >
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="line-clamp-2 text-sm font-medium break-words group-hover:underline" title={name}>
                      {name}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {formatSize(file.size)}, {uses === 0 ? "not used yet" : `${uses} ${uses === 1 ? "lecture" : "lectures"}`}
                    </span>
                  </span>
                  <EyeIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                  <span className="sr-only">Open {name}</span>
                </button>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">
          No readings yet. Add the books or papers the syllabus cites.
        </p>
      )}

      <div className="flex flex-col gap-2">
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.doc,.docx,.ppt,.pptx"
          className="sr-only"
          tabIndex={-1}
          aria-hidden="true"
          onChange={(event) => {
            add(Array.from(event.target.files ?? []));
            event.target.value = "";
          }}
        />
        <Button variant="outline" disabled={step !== "idle"} onClick={() => inputRef.current?.click()}>
          {step === "idle" ? <UploadIcon /> : <Spinner />}
          {step === "uploading"
            ? "Uploading…"
            : step === "matching"
              ? "Matching to lectures…"
              : "Add readings"}
        </Button>
        {plan.books.length > 0 && (
          <Button variant="ghost" onClick={() => setBooksOpen(true)}>
            <BookOpenIcon />
            Match books to files
          </Button>
        )}
      </div>

      {plan.unassigned.length > 0 && (
        <div className="flex flex-col gap-2 border-t pt-4">
          <div className="flex items-center gap-2 text-sm font-medium">
            <InboxIcon className="size-4" aria-hidden="true" />
            Unassigned
          </div>
          <p className="text-sm text-muted-foreground">
            Attached to lectures that are no longer in the syllabus. Add them to a lecture from its
            Add material button.
          </p>
          <ItemGroup className="gap-2">
            {plan.unassigned.map((file) => (
              <FileRow
                key={file.path}
                file={file}
                label="Dismiss"
                onRemove={() => update(() => dismissUnassigned(plan.course, file.path))}
              />
            ))}
          </ItemGroup>
        </div>
      )}

      <Dialog open={booksOpen} onOpenChange={setBooksOpen}>
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>Match books to files</DialogTitle>
            <DialogDescription>
              Which uploaded file holds each book the syllabus cites. After a change, match the
              readings again; excerpts you already decided on stay.
            </DialogDescription>
          </DialogHeader>
          <BooksPanel plan={plan} readingFiles={readingFiles} update={update} />
          <div className="flex justify-end">
            <Button
              disabled={busy || step !== "idle"}
              onClick={async () => {
                setStep("matching");
                await update(() => autoMatch(plan.course));
                setStep("idle");
              }}
            >
              {step === "matching" && <Spinner />}
              {step === "matching" ? "Matching…" : "Match readings again"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </aside>
  );
}
