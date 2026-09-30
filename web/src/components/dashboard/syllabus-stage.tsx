"use client";

import { useEffect, useState } from "react";
import {
  CircleAlertIcon,
  EyeIcon,
  RefreshCwIcon,
  ScrollTextIcon,
  SparklesIcon,
  Trash2Icon,
} from "lucide-react";
import { toast } from "sonner";

import { useFileViewer } from "@/components/dashboard/file-viewer";
import { ReadingList, ReadingText, TranscriptNotes } from "@/components/dashboard/transcript-parts";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Field, FieldContent, FieldDescription, FieldLabel, FieldTitle } from "@/components/ui/field";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
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

type SyllabusStageProps = {
  files: SavedFile[];
  plan: PlanView | null;
  onPlan: (plan: PlanView) => void;
  onReload: () => void;
  onDeleted: () => void;
};

function errorMessage(err: unknown) {
  return err instanceof ApiError ? err.message : "Couldn't reach the server. Please try again.";
}

function plural(count: number, one: string, many: string) {
  return `${count} ${count === 1 ? one : many}`;
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
              {name} and its session plan will be removed from storage.
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

function SessionPlan({ transcript }: { transcript: Transcript }) {
  const materials = transcript.learning_materials;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Session plan</CardTitle>
        <CardDescription>
          {plural(transcript.sessions.length, "session", "sessions")} ·{" "}
          {plural(materials.length, "course material", "course materials")}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <TranscriptNotes transcript={transcript} />
        <Accordion>
          {materials.length > 0 && (
            <AccordionItem value="materials">
              <AccordionTrigger>Course materials ({materials.length})</AccordionTrigger>
              <AccordionContent>
                <ol className="flex list-decimal flex-col gap-1 pl-5">
                  {materials.map((reading, index) => (
                    <li key={index}>
                      <ReadingText reading={reading} />
                    </li>
                  ))}
                </ol>
              </AccordionContent>
            </AccordionItem>
          )}
          {transcript.sessions.map((session, index) => (
            <AccordionItem key={index} value={`session-${index}`}>
              <AccordionTrigger>
                <span className="flex flex-col gap-0.5">
                  <span>
                    {session.label} · {session.topic}
                  </span>
                  {session.date && (
                    <span className="font-normal text-muted-foreground">{session.date}</span>
                  )}
                </span>
              </AccordionTrigger>
              <AccordionContent className="flex flex-col gap-2">
                {session.subtopics.length > 0 && (
                  <ul className="list-disc pl-5 text-muted-foreground">
                    {session.subtopics.map((subtopic, i) => (
                      <li key={i}>{subtopic}</li>
                    ))}
                  </ul>
                )}
                <ReadingList
                  title="Required"
                  readings={session.required_readings}
                  materials={materials}
                />
                <ReadingList
                  title="Optional"
                  readings={session.optional_readings}
                  materials={materials}
                />
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
        {transcript.sessions.length === 0 && (
          <p className="text-sm text-muted-foreground">No sessions found in this syllabus.</p>
        )}
      </CardContent>
    </Card>
  );
}

function SessionPlanLoading() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Spinner />
          Reading the syllabus…
        </CardTitle>
        <CardDescription>This usually takes up to a minute.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {Array.from({ length: 4 }, (_, index) => (
          <Skeleton key={index} className="h-10 w-full" />
        ))}
      </CardContent>
    </Card>
  );
}

export function SyllabusStage({ files, plan, onPlan, onReload, onDeleted }: SyllabusStageProps) {
  const openFile = useFileViewer();
  const [choice, setChoice] = useState<string | null>(null);
  const [transcripts, setTranscripts] = useState<Record<string, Transcript | null>>({});
  const [extracting, setExtracting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const readablePaths = files.map((file) => file.path).filter((path) => TRANSCRIBABLE.test(path));
  const readableKey = readablePaths.join("\n");

  useEffect(() => {
    let cancelled = false;
    for (const path of readableKey.split("\n").filter(Boolean)) {
      getTranscript(path).then(
        (transcript) => !cancelled && setTranscripts((prev) => ({ ...prev, [path]: transcript })),
        () => !cancelled && setTranscripts((prev) => ({ ...prev, [path]: null })),
      );
    }
    return () => {
      cancelled = true;
    };
  }, [readableKey]);

  const selected =
    choice && readablePaths.includes(choice)
      ? choice
      : plan?.primary && readablePaths.includes(plan.primary)
        ? plan.primary
        : (readablePaths[0] ?? null);
  const transcript = selected ? transcripts[selected] : undefined;

  const makePrimary = async (path: string) => {
    try {
      onPlan(await setPrimarySyllabus(plan?.course ?? path.split("/")[0], path));
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const select = (path: string) => {
    setChoice(path);
    setError(null);
    if (transcripts[path] && plan?.primary !== path) makePrimary(path);
  };

  const extract = async (path: string, force: boolean) => {
    setExtracting(path);
    setError(null);
    try {
      const result = await transcribeSyllabus(path, force);
      setTranscripts((prev) => ({ ...prev, [path]: result }));
      if (plan?.primary && plan.primary !== path) await makePrimary(path);
      else onReload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setExtracting(null);
    }
  };

  const status = (path: string) => {
    if (!TRANSCRIBABLE.test(path)) return "Only PDF and DOCX files can be read.";
    if (extracting === path) return "Reading…";
    const found = transcripts[path];
    if (found === undefined) return "Checking…";
    if (found === null) return "Not read yet";
    return plural(found.sessions.length, "session", "sessions");
  };

  if (files.length === 0) {
    return (
      <Empty className="border border-dashed">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <ScrollTextIcon />
          </EmptyMedia>
          <EmptyTitle>No syllabus uploaded</EmptyTitle>
          <EmptyDescription>Go back to the first stage and upload the syllabus.</EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Syllabus</CardTitle>
          {selected && transcript !== undefined && (
            <CardAction>
              {transcript === null ? (
                <Button disabled={extracting !== null} onClick={() => extract(selected, false)}>
                  {extracting === selected ? <Spinner /> : <SparklesIcon />}
                  {extracting === selected ? "Reading…" : "Extract session plan"}
                </Button>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={extracting !== null}
                  onClick={() => extract(selected, true)}
                >
                  {extracting === selected ? <Spinner /> : <RefreshCwIcon />}
                  {extracting === selected ? "Reading…" : "Read again"}
                </Button>
              )}
            </CardAction>
          )}
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <RadioGroup value={selected} onValueChange={(value) => select(value as string)}>
            {files.map((file) => {
              const name = fileName(file.path);
              const isPrimary = plan?.primary === file.path;
              return (
                <FieldLabel key={file.path}>
                  <Field orientation="horizontal">
                    <RadioGroupItem
                      value={file.path}
                      disabled={!TRANSCRIBABLE.test(file.path) || extracting !== null}
                    />
                    <FieldContent className="min-w-0">
                      <FieldTitle className="w-full min-w-0">
                        <span className="truncate" title={name}>
                          {name}
                        </span>
                      </FieldTitle>
                      <FieldDescription>{status(file.path)}</FieldDescription>
                    </FieldContent>
                    <div
                      className="flex shrink-0 items-center"
                      onClick={(event) => {
                        if (event.currentTarget.contains(event.target as Node)) {
                          event.preventDefault();
                        }
                      }}
                    >
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`Open ${name}`}
                        onClick={() => openFile({ path: file.path })}
                      >
                        <EyeIcon />
                      </Button>
                      <DeleteSyllabusButton
                        file={file}
                        isPrimary={isPrimary}
                        onDeleted={onDeleted}
                      />
                    </div>
                  </Field>
                </FieldLabel>
              );
            })}
          </RadioGroup>

          {error && (
            <Alert variant="destructive">
              <CircleAlertIcon />
              <AlertTitle>Couldn&apos;t read the syllabus</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

      {extracting === selected && extracting !== null ? (
        <SessionPlanLoading />
      ) : (
        transcript && <SessionPlan transcript={transcript} />
      )}
    </div>
  );
}
