"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronDownIcon, FileTextIcon } from "lucide-react";
import { toast } from "sonner";

import { estimatedExcerpts, missingPages } from "@/components/course/auto-match";
import { AddMaterialDialog } from "@/components/dashboard/add-material-dialog";
import { FileRow } from "@/components/dashboard/course-plan";
import { SessionProposals } from "@/components/dashboard/mapping-parts";
import { TOPIC_STATUS } from "@/components/dashboard/notes-stage";
import { ReadingList } from "@/components/dashboard/transcript-parts";
import { Badge } from "@/components/ui/badge";
import { ItemGroup } from "@/components/ui/item";
import {
  ApiError,
  detachFile,
  previewPath,
  type NotesRunView,
  type PlanView,
  type SavedFile,
  type SessionView,
  type TopicNote,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type LectureListProps = {
  plan: PlanView;
  courseId?: number;
  readingFiles: SavedFile[];
  notes: NotesRunView | null;
  onPlan: (plan: PlanView) => void;
  onUploaded: () => void;
};

function plural(count: number, one: string, many: string) {
  return `${count} ${count === 1 ? one : many}`;
}

/** Each topic under the first lecture it covers; the others only mention it. */
function topicsByLecture(notes: NotesRunView | null) {
  const first = new Map<number, TopicNote[]>();
  const also = new Map<number, TopicNote[]>();
  const unplaced: TopicNote[] = [];
  const sessions = notes?.topic_sessions ?? {};
  for (const note of notes?.document?.sections.flatMap((s) => s.topics) ?? []) {
    const covered = sessions[note.topic_id] ?? [];
    if (covered.length === 0) {
      unplaced.push(note);
      continue;
    }
    first.set(covered[0], [...(first.get(covered[0]) ?? []), note]);
    for (const index of covered.slice(1)) also.set(index, [...(also.get(index) ?? []), note]);
  }
  return { first, also, unplaced };
}

function NoteLink({ course, run, note }: { course: string; run: string; note: TopicNote }) {
  const status = TOPIC_STATUS[note.status];
  return (
    <li>
      <Link
        href={previewPath(course, run, note.topic_id)}
        className="flex min-h-11 items-center gap-3 rounded-md px-2 py-1.5 transition-colors hover:bg-muted"
      >
        <FileTextIcon className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <span className="min-w-0 flex-1">
          <span className="text-muted-foreground tabular-nums">{note.topic_id}</span> {note.title}
        </span>
        {note.teacher_decision?.decision === "approved" && <Badge>Teacher approved</Badge>}
        <Badge className={status.className}>{status.label}</Badge>
      </Link>
    </li>
  );
}

function LectureDetails({
  entry,
  plan,
  courseId,
  readingFiles,
  onPlan,
  onUploaded,
}: Omit<LectureListProps, "notes"> & { entry: SessionView }) {
  const [busy, setBusy] = useState(false);
  const transcript = plan.transcript!;
  const update = async (action: () => Promise<PlanView>) => {
    if (busy) return;
    setBusy(true);
    try {
      onPlan(await action());
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't reach the server.");
    } finally {
      setBusy(false);
    }
  };
  const { session } = entry;

  return (
    <div className="flex flex-col gap-4 pt-2 pb-4">
      {session.subtopics.length > 0 && (
        <ul className="list-disc pl-5 text-sm text-muted-foreground">
          {session.subtopics.map((subtopic, index) => (
            <li key={index}>{subtopic}</li>
          ))}
        </ul>
      )}
      <ReadingList
        title="Required in the syllabus"
        readings={session.required_readings}
        materials={transcript.learning_materials}
      />
      <ReadingList
        title="Optional in the syllabus"
        readings={session.optional_readings}
        materials={transcript.learning_materials}
      />
      <SessionProposals proposals={entry.proposals} course={plan.course} update={update} />
      <div className="flex flex-col gap-2">
        <span className="text-xs font-medium text-muted-foreground">
          Readings the notes are written from
        </span>
        {entry.files.length > 0 ? (
          <ItemGroup className="gap-2">
            {entry.files.map((file) => (
              <FileRow
                key={file.path}
                file={file}
                label="Detach"
                onRemove={() => update(() => detachFile(plan.course, entry.id, file.path))}
              />
            ))}
          </ItemGroup>
        ) : (
          <p className="text-sm text-muted-foreground">None yet.</p>
        )}
        <div>
          <AddMaterialDialog
            course={plan.course}
            courseId={courseId}
            entry={entry}
            readingFiles={readingFiles}
            onPlan={onPlan}
            onUploaded={onUploaded}
          />
        </div>
      </div>
    </div>
  );
}

/** The course as its syllabus reads: numbered lectures, each with the notes written for it. */
export function LectureList({ notes, ...props }: LectureListProps) {
  const { plan } = props;
  const [open, setOpen] = useState<Set<string>>(new Set());
  const { first, also, unplaced } = topicsByLecture(notes);
  const run = notes?.run.id;

  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="flex flex-col gap-6">
      <ol aria-label="Lectures" className="flex flex-col border-t">
        {plan.sessions.map((entry, index) => {
          const { session } = entry;
          const expanded = open.has(entry.id);
          const estimated = estimatedExcerpts(entry).length;
          const missing = missingPages(entry).length;
          const lectureNotes = first.get(index) ?? [];
          const covered = also.get(index) ?? [];
          const panel = `lecture-${entry.id}`;
          return (
            <li key={entry.id} className="border-b">
              <button
                type="button"
                aria-expanded={expanded}
                aria-controls={panel}
                onClick={() => toggle(entry.id)}
                className="grid w-full grid-cols-[3rem_minmax(0,1fr)_auto] items-start gap-x-3 py-4 text-left transition-colors hover:bg-muted/60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
              >
                <span className="text-2xl leading-none font-bold tabular-nums">
                  {session.number ?? index + 1}
                </span>
                <span className="flex min-w-0 flex-col gap-1">
                  <span className="font-medium">
                    {session.topic || session.label}
                  </span>
                  <span className="text-sm text-muted-foreground">
                    {[session.topic ? session.label : null, session.date].filter(Boolean).join(", ")}
                  </span>
                  <span className="flex flex-wrap gap-1.5 pt-1">
                    <Badge variant="outline">
                      {entry.files.length > 0
                        ? plural(entry.files.length, "reading", "readings")
                        : "No readings"}
                    </Badge>
                    {estimated > 0 && (
                      <Badge className="bg-warning/15 text-warning">Check pages</Badge>
                    )}
                    {missing > 0 && (
                      <Badge className="bg-destructive/10 text-destructive">
                        {plural(missing, "citation", "citations")} not found
                      </Badge>
                    )}
                  </span>
                </span>
                <ChevronDownIcon
                  aria-hidden="true"
                  className={cn(
                    "mt-1 size-5 text-muted-foreground transition-transform",
                    expanded && "rotate-180",
                  )}
                />
              </button>

              {run && (lectureNotes.length > 0 || covered.length > 0) && (
                <div className="ml-12 flex flex-col gap-1 border-l pb-3 pl-3">
                  <ul aria-label={`Notes for ${session.label}`} className="flex flex-col">
                    {lectureNotes.map((note) => (
                      <NoteLink key={note.topic_id} course={plan.course} run={run} note={note} />
                    ))}
                  </ul>
                  {covered.length > 0 && (
                    <p className="px-2 text-sm text-muted-foreground">
                      Also covered in {covered.map((n) => n.topic_id).join(", ")}
                    </p>
                  )}
                </div>
              )}

              <div id={panel} hidden={!expanded} className="ml-12 pl-3">
                {expanded && <LectureDetails entry={entry} {...props} />}
              </div>
            </li>
          );
        })}
      </ol>

      {run && unplaced.length > 0 && (
        <section aria-labelledby="other-notes" className="flex flex-col gap-2">
          <h2 id="other-notes" className="text-base">
            Notes not linked to a lecture
          </h2>
          <ul className="flex flex-col">
            {unplaced.map((note) => (
              <NoteLink key={note.topic_id} course={plan.course} run={run} note={note} />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
