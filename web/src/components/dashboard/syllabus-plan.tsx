"use client";

import { useEffect, useState } from "react";
import {
  CircleAlertIcon,
  RefreshCwIcon,
  SparklesIcon,
  StarIcon,
  Trash2Icon,
} from "lucide-react";
import { toast } from "sonner";

import { CoursePlan } from "@/components/dashboard/course-plan";
import {
  CourseMaterialsList,
  SessionBlock,
  TranscriptNotes,
} from "@/components/dashboard/transcript-parts";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  ApiError,
  deleteSyllabus,
  fileName,
  getTranscript,
  setPrimarySyllabus,
  transcribeSyllabus,
  type PlanView,
  type SavedFile,
  type Transcript,
} from "@/lib/api";

const TRANSCRIBABLE = /\.(pdf|docx)$/i;

type Status =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "done"; transcript: Transcript }
  | { kind: "error"; message: string };

type PlanProps = {
  plan: PlanView | null;
  courseId?: number;
  readingFiles: SavedFile[];
  onPlan: (plan: PlanView) => void;
  onUploaded: () => void;
  onReload: () => void;
  onDeleted: () => void;
};

function errorMessage(err: unknown) {
  return err instanceof ApiError ? err.message : "Couldn't reach the server. Please try again.";
}

function TranscriptView({ transcript }: { transcript: Transcript }) {
  return (
    <div className="flex flex-col gap-4">
      <TranscriptNotes transcript={transcript} />
      <CourseMaterialsList transcript={transcript} />
      {transcript.sessions.length > 0 ? (
        <ol className="flex flex-col gap-2">
          {transcript.sessions.map((session, index) => (
            <SessionBlock key={index} session={session} />
          ))}
        </ol>
      ) : (
        <p className="text-sm text-muted-foreground">No session plan found.</p>
      )}
    </div>
  );
}

function DeleteSyllabusButton({
  file,
  isPrimary,
  onDeleted,
}: {
  file: SavedFile;
  isPrimary: boolean;
  onDeleted: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const name = fileName(file.path);

  const onDelete = async () => {
    setPending(true);
    try {
      await deleteSyllabus(file.path);
      setOpen(false);
      toast.success("Syllabus deleted", { description: name });
      onDeleted();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setPending(false);
    }
  };

  return (
    <>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label={`Delete ${name}`}
        onClick={() => setOpen(true)}
      >
        <Trash2Icon />
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete this syllabus?</DialogTitle>
            <DialogDescription>
              {name} and its transcript will be removed from storage.
              {isPrimary &&
                " It is the course plan: files attached to its sessions stay in the course and " +
                  "move to Unassigned."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose render={<Button type="button" variant="outline" />}>Cancel</DialogClose>
            <Button variant="destructive" disabled={pending} onClick={onDelete}>
              <Trash2Icon />
              {pending ? "Deleting…" : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function SyllabusFileCard({ file, ...props }: PlanProps & { file: SavedFile }) {
  const { plan, onPlan, onReload } = props;
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const name = fileName(file.path);
  const canTranscribe = TRANSCRIBABLE.test(name);
  const isPrimary = plan?.primary === file.path;

  useEffect(() => {
    if (!canTranscribe) return;
    let cancelled = false;
    getTranscript(file.path)
      .then((transcript) => !cancelled && setStatus({ kind: "done", transcript }))
      .catch(() => {
        // No transcript yet: stay idle.
      });
    return () => {
      cancelled = true;
    };
  }, [file.path, canTranscribe]);

  const transcribe = async (force: boolean) => {
    setStatus({ kind: "loading" });
    try {
      setStatus({ kind: "done", transcript: await transcribeSyllabus(file.path, force) });
      onReload();
    } catch (err) {
      setStatus({ kind: "error", message: errorMessage(err) });
    }
  };

  const makePrimary = async () => {
    try {
      onPlan(await setPrimarySyllabus(plan?.course ?? file.path.split("/")[0], file.path));
    } catch (err) {
      setStatus({ kind: "error", message: errorMessage(err) });
    }
  };

  const done = status.kind === "done";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex min-w-0 items-center gap-2">
          <span className="truncate" title={name}>
            {name}
          </span>
          {isPrimary && <Badge>Course plan</Badge>}
        </CardTitle>
        <CardDescription>
          {!canTranscribe
            ? "Only PDF and DOCX syllabi can be transcribed."
            : isPrimary
              ? "Attach materials to each session below."
              : "Extract the session plan and learning materials from this syllabus."}
        </CardDescription>
        <CardAction className="flex gap-2">
          {canTranscribe && (
            <>
              {done && !isPrimary && (
                <Button variant="outline" size="sm" onClick={makePrimary}>
                  <StarIcon />
                  Use as course plan
                </Button>
              )}
              <Button
                variant={done ? "outline" : "default"}
                size="sm"
                disabled={status.kind === "loading"}
                onClick={() => transcribe(done)}
              >
                {done ? <RefreshCwIcon /> : <SparklesIcon />}
                {status.kind === "loading" ? "Transcribing…" : done ? "Re-run" : "Transcribe"}
              </Button>
            </>
          )}
          <DeleteSyllabusButton file={file} isPrimary={isPrimary} onDeleted={props.onDeleted} />
        </CardAction>
      </CardHeader>

      {(done || status.kind === "error") && (
        <CardContent>
          {status.kind === "error" ? (
            <Alert variant="destructive">
              <CircleAlertIcon />
              <AlertTitle>Couldn&apos;t transcribe the syllabus</AlertTitle>
              <AlertDescription>{status.message}</AlertDescription>
            </Alert>
          ) : isPrimary && plan?.transcript ? (
            <CoursePlan
              plan={plan}
              courseId={props.courseId}
              readingFiles={props.readingFiles}
              onPlan={onPlan}
              onUploaded={props.onUploaded}
            />
          ) : (
            status.kind === "done" && <TranscriptView transcript={status.transcript} />
          )}
        </CardContent>
      )}
    </Card>
  );
}

export function SyllabusPlan({ files, ...props }: PlanProps & { files: SavedFile[] }) {
  if (files.length === 0) return null;
  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-lg font-semibold tracking-tight">Syllabus plan</h2>
      {files.map((file) => (
        <SyllabusFileCard key={file.path} file={file} {...props} />
      ))}
    </section>
  );
}
