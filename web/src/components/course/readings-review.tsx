"use client";

import { useState } from "react";
import { ArrowLeftIcon, CheckIcon } from "lucide-react";

import { estimatedExcerpts, missingPages } from "@/components/course/auto-match";
import { CoursePlan } from "@/components/dashboard/course-plan";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import type { PlanView, SavedFile, SessionView } from "@/lib/api";

type ReadingsReviewProps = {
  plan: PlanView;
  courseId?: number;
  readingFiles: SavedFile[];
  onPlan: (plan: PlanView) => void;
  onUploaded: () => void;
  /** Already approved: the screen was opened again from the course menu. */
  approved: boolean;
  onApprove: () => Promise<void>;
  onClose: () => void;
};

function plural(count: number, one: string, many: string) {
  return `${count} ${count === 1 ? one : many}`;
}

function needsAttention(entry: SessionView) {
  return (
    entry.files.length === 0 || estimatedExcerpts(entry).length > 0 || missingPages(entry).length > 0
  );
}

/**
 * Readings per lecture: each lecture's matched excerpts and files, the ones needing a look
 * first, then one approval that opens the notes.
 */
export function ReadingsReview({
  plan,
  courseId,
  readingFiles,
  onPlan,
  onUploaded,
  approved,
  onApprove,
  onClose,
}: ReadingsReviewProps) {
  const [approving, setApproving] = useState(false);
  const estimated = plan.sessions.filter((s) => estimatedExcerpts(s).length > 0).length;
  const missing = plan.sessions.filter((s) => missingPages(s).length > 0).length;
  const empty = plan.sessions.filter((s) => s.files.length === 0).length;
  const flagged = plan.sessions.filter(needsAttention).length;
  // Display order only: lectures needing attention first, each group in syllabus order.
  const ordered: PlanView = {
    ...plan,
    sessions: [
      ...plan.sessions.filter(needsAttention),
      ...plan.sessions.filter((s) => !needsAttention(s)),
    ],
  };

  const approve = async () => {
    setApproving(true);
    try {
      await onApprove();
    } finally {
      setApproving(false);
    }
  };

  return (
    <section aria-labelledby="readings-title" className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex max-w-2xl flex-col gap-1">
          <h2 id="readings-title" className="text-xl">
            Readings per lecture
          </h2>
          <p className="text-muted-foreground">
            Each lecture&apos;s note is written from these excerpts and files only.{" "}
            {flagged > 0
              ? `${plural(flagged, "lecture needs", "lectures need")} a look and ${flagged === 1 ? "comes" : "come"} first.`
              : "Every lecture has readings with exact pages."}
          </p>
          {flagged > 0 && (
            <ul className="flex flex-wrap gap-x-4 gap-y-1 pt-1 text-sm">
              {estimated > 0 && (
                <li className="text-warning">{plural(estimated, "lecture", "lectures")}: check pages</li>
              )}
              {missing > 0 && (
                <li className="text-destructive">
                  {plural(missing, "lecture", "lectures")}: a citation not found
                </li>
              )}
              {empty > 0 && (
                <li className="text-muted-foreground">
                  {plural(empty, "lecture", "lectures")} without readings
                </li>
              )}
            </ul>
          )}
        </div>
        {approved ? (
          <Button size="lg" variant="outline" onClick={onClose}>
            <ArrowLeftIcon />
            Back to the notes
          </Button>
        ) : (
          <Button size="lg" disabled={approving} onClick={approve}>
            {approving ? <Spinner /> : <CheckIcon />}
            Approve readings
          </Button>
        )}
      </div>

      <CoursePlan
        plan={ordered}
        courseId={courseId}
        readingFiles={readingFiles}
        onPlan={onPlan}
        onUploaded={onUploaded}
      />
    </section>
  );
}
