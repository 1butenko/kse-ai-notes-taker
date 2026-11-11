"use client";

import Link from "next/link";
import { ChevronRightIcon, FolderOpenIcon } from "lucide-react";

import {
  notesState,
  type CourseLectureNotes,
  type LectureNotesState,
} from "@/components/lecture-notes/use-course-lecture-notes";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { lecturePath, visualNotesPath, type PlanView } from "@/lib/api";

type LectureListProps = {
  plan: PlanView;
  notes: CourseLectureNotes;
};

export function NotesBadge({ state }: { state: LectureNotesState }) {
  switch (state) {
    case "writing":
      return (
        <Badge variant="secondary">
          <Spinner data-icon="inline-start" />
          Writing
        </Badge>
      );
    case "ready":
      return <Badge variant="secondary">Notes ready</Badge>;
    case "changed":
      return <Badge variant="outline">Readings changed</Badge>;
    case "failed":
      return <Badge variant="destructive">Failed</Badge>;
    case "none":
      return <Badge variant="outline">No notes</Badge>;
  }
}

/** The notes section: every lecture in syllabus order, with the state of its notes. */
export function LectureList({ plan, notes }: LectureListProps) {
  return (
    <ol aria-label="Lectures" className="flex flex-col border-t">
      {plan.sessions.map((entry, index) => {
        const { session } = entry;
        const status = notes.status(entry.id);
        const published = status?.published ?? null;
        const title = session.topic || session.label;
        const href = published
          ? visualNotesPath(plan.course, entry.id, published.id)
          : lecturePath(plan.course, entry.id);
        return (
          <li key={entry.id} className="flex items-stretch border-b">
            <Link
              href={href}
              className="grid min-w-0 flex-1 grid-cols-[3rem_minmax(0,1fr)_auto] items-start gap-x-3 -mx-3 rounded-md px-3 py-4 transition-colors hover:bg-muted/60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
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
                  {notes.loaded && <NotesBadge state={notesState(status)} />}
                  {entry.files.length === 0 && <Badge variant="outline">No readings</Badge>}
                </span>
              </span>
              <span className="flex items-center gap-1 pt-0.5 text-sm text-muted-foreground">
                {published ? "Open notes" : "Lecture page"}
                <ChevronRightIcon aria-hidden="true" className="size-4" />
              </span>
            </Link>
            {published && (
              <Link
                href={lecturePath(plan.course, entry.id)}
                aria-label={`Lecture ${session.number ?? index + 1}: readings and notes`}
                title="Lecture page"
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
