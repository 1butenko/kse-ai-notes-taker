"use client";

import Link from "next/link";
import { ChevronRightIcon, FolderOpenIcon } from "lucide-react";

import {
  lectureStatus,
  readingsChanged,
  type CourseNotes,
  type LectureNotes,
  type LectureStatus,
} from "@/components/course/use-course-notes";
import { TOPIC_STATUS } from "@/components/dashboard/notes-stage";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { lecturePath, previewPath, type PlanView } from "@/lib/api";

type LectureListProps = {
  plan: PlanView;
  notes: CourseNotes;
};

export function StatusBadge({ status, lecture }: { status: LectureStatus; lecture: LectureNotes }) {
  switch (status) {
    case "writing":
      return (
        <Badge className="bg-info/10 text-info">
          <Spinner className="size-3" />
          Writing
        </Badge>
      );
    case "queued":
      return <Badge variant="secondary">Queued</Badge>;
    case "verified":
      return <Badge className={TOPIC_STATUS.verified.className}>Verified</Badge>;
    case "unresolved":
      return <Badge className={TOPIC_STATUS.unresolved.className}>Unresolved</Badge>;
    case "note":
      return <Badge variant="outline">Note</Badge>;
    case "none":
      return (
        <>
          <Badge variant="outline">No note</Badge>
          {lecture.unfinished && (
            <Badge className="bg-destructive/10 text-destructive">
              {lecture.unfinished.error?.startsWith("Stopped") ? "Stopped" : "Failed"}
            </Badge>
          )}
        </>
      );
  }
}

/** The notes section: every lecture in syllabus order, with the state of its note. */
export function LectureList({ plan, notes }: LectureListProps) {
  return (
    <ol aria-label="Lectures" className="flex flex-col border-t">
      {plan.sessions.map((entry, index) => {
        const { session } = entry;
        const lecture = notes.lecture(entry.id);
        const status = lectureStatus(lecture);
        const title = session.topic || session.label;
        const href = lecture.note
          ? previewPath(plan.course, lecture.note.id)
          : lecturePath(plan.course, entry.id);
        return (
          <li key={entry.id} className="flex items-stretch border-b">
            <Link
              href={href}
              className="grid min-w-0 flex-1 grid-cols-[3rem_minmax(0,1fr)_auto] items-start gap-x-3 py-4 transition-colors hover:bg-muted/60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              <span className="text-2xl leading-none font-bold tabular-nums">
                {session.number ?? index + 1}
              </span>
              <span className="flex min-w-0 flex-col gap-1">
                <span className="font-medium">{title}</span>
                <span className="text-sm text-muted-foreground">
                  {[session.topic ? session.label : null, session.date].filter(Boolean).join(", ")}
                </span>
                <span className="flex flex-wrap gap-1.5 pt-1">
                  <StatusBadge status={status} lecture={lecture} />
                  {entry.files.length === 0 && <Badge variant="outline">No readings</Badge>}
                </span>
                {readingsChanged(lecture, entry) && (
                  <span className="text-sm text-warning">
                    Readings changed since this note was written
                  </span>
                )}
              </span>
              <span className="flex items-center gap-1 pt-0.5 text-sm text-muted-foreground">
                {lecture.note ? "Open note" : "Lecture page"}
                <ChevronRightIcon aria-hidden="true" className="size-4" />
              </span>
            </Link>
            {lecture.note && (
              <Link
                href={lecturePath(plan.course, entry.id)}
                aria-label={`Readings of lecture ${session.number ?? index + 1}`}
                title="Lecture readings"
                className={buttonVariants({
                  variant: "ghost",
                  size: "icon",
                  className: "mt-3 ml-1",
                })}
              >
                <FolderOpenIcon />
              </Link>
            )}
          </li>
        );
      })}
    </ol>
  );
}
