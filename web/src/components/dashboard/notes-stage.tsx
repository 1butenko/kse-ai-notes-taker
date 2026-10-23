"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  CircleAlertIcon,
  ExternalLinkIcon,
  FileCodeIcon,
  FileTextIcon,
  NotebookPenIcon,
  RotateCwIcon,
  SparklesIcon,
  TriangleAlertIcon,
} from "lucide-react";
import { toast } from "sonner";

import { useFileViewer } from "@/components/dashboard/file-viewer";
import { artifactRevision, RevisionTag } from "@/components/notes/artifact-revision";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemTitle,
} from "@/components/ui/item";
import { Progress, ProgressLabel, ProgressValue } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import {
  ApiError,
  generateNotes,
  getNotesRun,
  listNotesRuns,
  notesFileUrl,
  previewPath,
  revisionArtifactUrl,
  type NotesDocument,
  type NotesRun,
  type NotesRunView,
  type TopicNote,
  type TopicStatus,
} from "@/lib/api";

const POLL_MS = 3000;

const STAGE_LABELS: Record<string, string> = {
  queued: "Queued",
  inputs: "Reading the session materials",
  planning: "Planning topics and checking coverage",
  topics: "Writing and verifying topics",
  composition: "Harmonizing notation and cross-references",
  rendering: "Rendering HTML and PDF",
};

const STAGE_NAMES: Record<string, string> = {
  planner: "Planner",
  coverage: "Coverage checker",
  selector: "Evidence selector",
  writer: "Writer",
  verifier: "Verifier",
  escalation: "Escalated verifier",
  consistency: "Consistency",
};

export const TOPIC_STATUS: Record<TopicStatus, { label: string; className: string }> = {
  verified: { label: "Verified", className: "bg-success/10 text-success" },
  unresolved: { label: "Unresolved", className: "bg-warning/15 text-warning" },
  no_evidence: { label: "No evidence", className: "bg-secondary text-secondary-foreground" },
  failed: { label: "Failed", className: "bg-destructive/10 text-destructive" },
};

function errorMessage(err: unknown) {
  return err instanceof ApiError ? err.message : "Couldn't reach the server. Please try again.";
}

function plural(count: number, one: string, many: string) {
  return `${count} ${count === 1 ? one : many}`;
}

function when(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function isActive(run: NotesRun) {
  return run.status === "queued" || run.status === "running";
}

function percent(run: NotesRun) {
  if (run.stage === "planning") return 10;
  if (run.stage === "topics") {
    return 20 + Math.round((70 * run.topics_done) / Math.max(run.topics_total, 1));
  }
  if (run.stage === "composition") return 92;
  if (run.stage === "rendering") return 97;
  return 4;
}

function RunProgress({ run }: { run: NotesRun }) {
  const last = run.events.at(-1);
  return (
    <div className="flex flex-col gap-2 rounded-lg border p-4">
      <Progress value={percent(run)}>
        <ProgressLabel className="flex items-center gap-2">
          <Spinner />
          {STAGE_LABELS[run.stage] ?? run.stage}
        </ProgressLabel>
        <ProgressValue />
      </Progress>
      <p className="text-sm text-muted-foreground">
        {run.topics_total > 0 && `${run.topics_done} of ${plural(run.topics_total, "topic", "topics")} done. `}
        {last?.message}
      </p>
    </div>
  );
}

function TopicRow({ note, onOpen }: { note: TopicNote; onOpen?: () => void }) {
  const status = TOPIC_STATUS[note.status];
  const sources = new Set(note.evidence.map((e) => e.title));
  const details =
    note.status === "failed"
      ? note.error
      : note.status === "no_evidence"
        ? "No excerpt of the session materials matched this topic."
        : [
            plural(note.blocks.length, "block", "blocks"),
            plural(note.evidence.length, "excerpt", "excerpts"),
            plural(sources.size, "source", "sources"),
            note.verifier &&
              `checked by ${note.verifier} in ${plural(note.rounds, "round", "rounds")}`,
          ]
            .filter(Boolean)
            .join(" · ");
  return (
    <Item variant="outline" size="sm">
      <ItemContent className="min-w-0">
        <ItemTitle>
          <span className="text-muted-foreground">{note.topic_id}</span>
          {note.title}
        </ItemTitle>
        <ItemDescription>{details}</ItemDescription>
        {note.open_issues.length > 0 && (
          <ul className="list-disc pl-5 text-sm text-muted-foreground">
            {note.open_issues.map((issue, i) => (
              <li key={i}>{issue.detail}</li>
            ))}
          </ul>
        )}
      </ItemContent>
      <ItemActions>
        {note.verification_stale && (
          <Badge variant="outline" title="Edited after its last check">
            Verification outdated
          </Badge>
        )}
        <Badge className={status.className}>{status.label}</Badge>
        {onOpen && (
          <Button variant="outline" size="sm" onClick={onOpen}>
            <FileTextIcon />
            Open
          </Button>
        )}
      </ItemActions>
    </Item>
  );
}

function DocumentOutline({
  document,
  onOpenTopic,
}: {
  document: NotesDocument;
  onOpenTopic: (note: TopicNote) => (() => void) | undefined;
}) {
  const notes = document.sections.flatMap((s) => s.topics);
  const counts = notes.reduce<Partial<Record<TopicStatus, number>>>((acc, note) => {
    acc[note.status] = (acc[note.status] ?? 0) + 1;
    return acc;
  }, {});
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-medium">{document.title}</h3>
        {(Object.keys(TOPIC_STATUS) as TopicStatus[])
          .filter((status) => counts[status])
          .map((status) => (
            <Badge key={status} className={TOPIC_STATUS[status].className}>
              {counts[status]} {TOPIC_STATUS[status].label.toLowerCase()}
            </Badge>
          ))}
      </div>
      <Accordion multiple defaultValue={document.sections.map((_, i) => i)}>
        {document.sections.map((section, i) => (
          <AccordionItem key={i} value={i}>
            <AccordionTrigger>
              {section.title}
              <span className="ml-auto pr-2 text-muted-foreground">
                {plural(section.topics.length, "topic", "topics")}
              </span>
            </AccordionTrigger>
            <AccordionContent>
              <ItemGroup className="gap-2">
                {section.topics.map((note) => (
                  <TopicRow key={note.topic_id} note={note} onOpen={onOpenTopic(note)} />
                ))}
              </ItemGroup>
            </AccordionContent>
          </AccordionItem>
        ))}
      </Accordion>
    </div>
  );
}

function RunDetails({ run }: { run: NotesRun }) {
  return (
    <Accordion>
      <AccordionItem value="activity">
        <AccordionTrigger>Models and activity</AccordionTrigger>
        <AccordionContent className="flex flex-col gap-4">
          <div className="flex flex-wrap gap-2">
            {Object.entries(run.models).map(([stage, model]) => (
              <Badge key={stage} variant="outline">
                {STAGE_NAMES[stage] ?? stage}: {model}
              </Badge>
            ))}
          </div>
          <ol className="flex flex-col gap-1 text-sm">
            {run.events.map((event, i) => (
              <li key={i} className="flex gap-3">
                <span className="shrink-0 text-muted-foreground tabular-nums">
                  {new Date(event.at).toLocaleTimeString()}
                </span>
                <span>{event.message}</span>
              </li>
            ))}
          </ol>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}

type NotesStageProps = {
  course: string;
  hasMaterials: boolean;
  onDoneChange: (done: boolean) => void;
};

export function NotesStage({ course, hasMaterials, onDoneChange }: NotesStageProps) {
  const router = useRouter();
  const openFile = useFileViewer();
  const [runs, setRuns] = useState<NotesRun[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [view, setView] = useState<NotesRunView | null>(null);
  const [starting, setStarting] = useState(false);

  const remember = useCallback((next: NotesRunView) => {
    setView(next);
    setRuns((prev) => {
      const others = (prev ?? []).filter((r) => r.id !== next.run.id);
      return [next.run, ...others].sort((a, b) => b.id.localeCompare(a.id));
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    listNotesRuns(course).then(
      (loaded) => {
        if (cancelled) return;
        setRuns(loaded);
        setSelected(loaded[0]?.id ?? null);
      },
      () => !cancelled && setRuns([]),
    );
    return () => {
      cancelled = true;
    };
  }, [course]);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    getNotesRun(course, selected).then(
      (loaded) => !cancelled && remember(loaded),
      (err) => !cancelled && toast.error(errorMessage(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [course, selected, remember]);

  const run = view?.run.id === selected ? view.run : null;
  const polling = run !== null && isActive(run);
  const textRevision = view?.current_revision ?? 0;
  const pdfRevision = artifactRevision(view?.artifacts ?? [], "pdf", null);
  const fileTitle = (title: string, revision: number) =>
    `${title} · PDF revision ${revision}` +
    (revision < textRevision ? ` (older than text revision ${textRevision})` : "");

  useEffect(() => {
    if (!polling || !selected) return;
    const timer = setInterval(() => {
      getNotesRun(course, selected).then(remember, () => {});
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [polling, course, selected, remember]);

  const latestDone = runs?.some((r) => r.status === "done") ?? false;
  useEffect(() => onDoneChange(latestDone), [latestDone, onDoneChange]);

  const start = async (resume?: string) => {
    setStarting(true);
    try {
      const started = await generateNotes(course, resume);
      remember(started);
      setSelected(started.run.id);
      toast.success(resume ? "Notes run resumed" : "Notes generation started");
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setStarting(false);
    }
  };

  const anyActive = runs?.some(isActive) ?? false;
  const canStart = hasMaterials && !starting && !anyActive;

  if (runs === null) {
    return <Skeleton className="h-64 w-full" />;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Lecture notes</CardTitle>
        <CardDescription>
          Topics are planned from the syllabus, written from all of their readings, checked
          against the sources, and rendered for reading and printing.
        </CardDescription>
        {runs.length > 0 && (
          <CardAction>
            <Button disabled={!canStart} onClick={() => start()}>
              {starting ? <Spinner /> : <SparklesIcon />}
              Generate again
            </Button>
          </CardAction>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        {runs.length === 0 ? (
          <Empty className="border border-dashed">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <NotebookPenIcon />
              </EmptyMedia>
              <EmptyTitle>No notes yet</EmptyTitle>
              <EmptyDescription>
                {hasMaterials
                  ? "Generation takes several minutes. You can leave this page and come back."
                  : "Attach materials or approve excerpts for the sessions first."}
              </EmptyDescription>
            </EmptyHeader>
            <Button disabled={!canStart} onClick={() => start()}>
              {starting ? <Spinner /> : <SparklesIcon />}
              Generate notes
            </Button>
          </Empty>
        ) : (
          <>
            <Select
              value={selected}
              onValueChange={(value) => value && setSelected(value)}
              items={runs.map((r) => ({
                value: r.id,
                label: `${when(r.created_at)} · ${r.status}`,
              }))}
            >
              <SelectTrigger className="w-full sm:w-72" aria-label="Notes run">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {runs.map((r) => (
                  <SelectItem key={r.id} value={r.id}>
                    {when(r.created_at)} · {r.status}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            {run === null ? (
              <Skeleton className="h-24 w-full" />
            ) : (
              <>
                {isActive(run) && <RunProgress run={run} />}

                {run.status === "failed" && (
                  <Alert variant="destructive">
                    <CircleAlertIcon />
                    <AlertTitle>Generation failed</AlertTitle>
                    <AlertDescription className="flex flex-col items-start gap-3">
                      {run.error}
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={!canStart}
                        onClick={() => start(run.id)}
                      >
                        <RotateCwIcon />
                        Resume this run
                      </Button>
                    </AlertDescription>
                  </Alert>
                )}

                {run.status === "done" && (
                  <div className="flex flex-wrap gap-2">
                    <Link href={previewPath(course, run.id)} className={buttonVariants()}>
                      <ExternalLinkIcon />
                      Read notes
                    </Link>
                    <Button
                      variant="outline"
                      disabled={!view?.pdf}
                      onClick={() =>
                        openFile({
                          path: "notes.pdf",
                          title: fileTitle(view?.document?.title ?? "Lecture notes", pdfRevision),
                          url: revisionArtifactUrl(course, run.id, pdfRevision, "pdf"),
                        })
                      }
                    >
                      <FileTextIcon />
                      Open PDF
                      <RevisionTag revision={pdfRevision} text={textRevision} />
                    </Button>
                    {/* The Quarto source at this URL is the original generation's. */}
                    <a
                      href={notesFileUrl(course, run.id, "qmd")}
                      download
                      className={buttonVariants({ variant: "outline" })}
                    >
                      <FileCodeIcon />
                      Quarto source
                      <RevisionTag revision={0} text={textRevision} />
                    </a>
                    {textRevision > 0 && (
                      <p className="basis-full text-sm text-muted-foreground">
                        Text revision {textRevision}. Files marked older were rendered before the
                        latest saved edits and don&apos;t include them.
                      </p>
                    )}
                    {view?.document?.sections.some((s) =>
                      s.topics.some((t) => t.status === "failed"),
                    ) && (
                      <p className="basis-full text-sm text-muted-foreground">
                        Some topics failed. A completed run keeps its saved notes, so generate
                        again to retry them in a new run.
                      </p>
                    )}
                  </div>
                )}

                {run.warnings.length > 0 && (
                  <Alert className="border-warning/40">
                    <TriangleAlertIcon className="text-warning" />
                    <AlertTitle>{plural(run.warnings.length, "warning", "warnings")}</AlertTitle>
                    <AlertDescription>
                      <ul className="list-disc pl-5">
                        {run.warnings.map((warning, i) => (
                          <li key={i}>{warning}</li>
                        ))}
                      </ul>
                    </AlertDescription>
                  </Alert>
                )}

                {view?.document && (
                  <DocumentOutline
                    document={view.document}
                    onOpenTopic={(note) =>
                      view.artifacts?.some(
                        (a) => a.topic_id === note.topic_id && a.format === "html" && a.status === "ready",
                      )
                        ? () => router.push(previewPath(course, run.id, note.topic_id))
                        : view.topic_pdfs.includes(note.topic_id)
                          ? () =>
                              openFile({
                                path: `${note.topic_id}.pdf`,
                                title: fileTitle(
                                  note.title,
                                  artifactRevision(view.artifacts ?? [], "pdf", note.topic_id),
                                ),
                                url: revisionArtifactUrl(
                                  course,
                                  run.id,
                                  artifactRevision(view.artifacts ?? [], "pdf", note.topic_id),
                                  "pdf",
                                  note.topic_id,
                                ),
                              })
                          : undefined
                    }
                  />
                )}

                <RunDetails run={run} />
              </>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
