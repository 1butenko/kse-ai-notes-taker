"use client";

import { useEffect, useState } from "react";
import { HistoryIcon, RotateCcwIcon } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import {
  ApiError,
  getNotesRevision,
  listNotesRevisions,
  restoreNotesRevision,
  type NotesDocument,
  type RevisionInfo,
  type RevisionView,
} from "@/lib/api";
import { cn } from "@/lib/utils";

import { diffDocuments } from "./diff";
import { TopicDiff } from "./revision-diff";

function errorMessage(err: unknown) {
  return err instanceof ApiError ? err.message : "Couldn't reach the server. Please try again.";
}

function when(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function originLabel(info: RevisionInfo): string {
  switch (info.origin) {
    case "generation":
      return "Generated";
    case "manual":
      return info.changed_topics.length > 0 ? "Manual edit" : "Language set";
    case "restore":
      return `Restored from revision ${info.restored_from}`;
    case "ai":
      return "AI suggestion";
    case "verification":
      return "Verification recorded";
  }
}

type RevisionHistoryProps = {
  course: string;
  run: string;
  /** HEAD as this page last loaded it; restores use it as their base. */
  revision: number;
  document: NotesDocument;
  /** Topics with an unsaved draft in this tab. */
  drafts: Set<string>;
  refresh: () => Promise<unknown>;
};

/** The committed history with block-level diffs, and restoring an earlier revision. */
export function RevisionHistory({ course, run, revision, document, drafts, refresh }: RevisionHistoryProps) {
  const [revisions, setRevisions] = useState<RevisionInfo[] | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [picked, setPicked] = useState<number | null>(null);
  // Committed snapshots never change, so they are cached for the page's lifetime.
  const [views, setViews] = useState<Record<number, RevisionView>>({});
  const [restoring, setRestoring] = useState<number | null>(null);
  const [pending, setPending] = useState(false);
  const [restoreError, setRestoreError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listNotesRevisions(course, run).then(
      (loaded) => {
        if (cancelled) return;
        setRevisions(loaded);
        setFailed(null);
      },
      (err) => !cancelled && setFailed(errorMessage(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [course, run, revision]);

  const listed = revisions ?? [];
  const selected = listed.find((r) => r.revision === (picked ?? revision)) ?? listed.at(-1);
  const wanted = [selected?.revision, selected?.parent, restoring].filter(
    (n): n is number => n !== null && n !== undefined,
  );
  const missing = wanted.filter((n) => !views[n]).join(",");

  useEffect(() => {
    if (!missing) return;
    let cancelled = false;
    Promise.all(missing.split(",").map((n) => getNotesRevision(course, run, Number(n)))).then(
      (loaded) => {
        if (cancelled) return;
        setViews((prev) => ({
          ...prev,
          ...Object.fromEntries(loaded.map((view) => [view.info.revision, view])),
        }));
      },
      (err) => !cancelled && toast.error(errorMessage(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [course, run, missing]);

  const shown = selected ? views[selected.revision] : undefined;
  const parent = selected?.parent !== null && selected ? views[selected.parent] : undefined;
  const changes = shown && parent ? diffDocuments(parent.document, shown.document) : [];

  const target = restoring !== null ? views[restoring] : undefined;
  const restored = target ? diffDocuments(document, target.document) : [];
  const affectedDrafts = restored.map((c) => c.topic_id).filter((id) => drafts.has(id));

  const restore = async () => {
    if (restoring === null) return;
    setPending(true);
    setRestoreError(null);
    try {
      const result = await restoreNotesRevision(course, run, restoring, revision);
      await refresh();
      if (result.revision.revision === revision) {
        toast.info(`Revision ${restoring} has the same text as the current revision`);
      } else {
        toast.success(`Restored revision ${restoring} as revision ${result.revision.revision}`);
        setPicked(result.revision.revision);
      }
      setRestoring(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) await refresh();
      setRestoreError(errorMessage(err));
    } finally {
      setPending(false);
    }
  };

  if (failed) {
    return <p className="text-sm text-destructive">Couldn&apos;t load the history: {failed}</p>;
  }
  if (revisions === null) return <Skeleton className="h-40 w-full" />;

  return (
    <section aria-label="Revision history" className="grid min-w-0 gap-4 lg:grid-cols-[18rem_1fr]">
      <ol aria-label="Revisions" className="flex flex-col gap-1">
        {[...revisions].reverse().map((info) => {
          const active = info.revision === selected?.revision;
          return (
            <li key={info.revision}>
              <button
                type="button"
                aria-pressed={active}
                onClick={() => setPicked(info.revision)}
                className={cn(
                  "flex w-full flex-col gap-0.5 rounded-lg border px-3 py-2 text-left text-sm transition-colors hover:bg-muted",
                  active && "border-primary/40 bg-muted",
                )}
              >
                <span className="flex flex-wrap items-center gap-2 font-medium">
                  Revision {info.revision}
                  {info.revision === revision && <Badge variant="secondary">Current</Badge>}
                </span>
                <span className="text-xs text-muted-foreground">
                  {originLabel(info)}
                  {info.changed_topics.length > 0 && ` · ${info.changed_topics.join(", ")}`}
                  {` · ${when(info.created_at)}`}
                </span>
              </button>
            </li>
          );
        })}
      </ol>

      {selected && (
        <section
          aria-label={`Changes in revision ${selected.revision}`}
          className="flex min-w-0 flex-col gap-4"
        >
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="flex items-center gap-2 font-medium">
              <HistoryIcon className="size-4" />
              Revision {selected.revision}: {originLabel(selected)}
            </h2>
            {selected.revision !== revision && (
              <Button
                size="sm"
                variant="outline"
                className="ml-auto"
                onClick={() => {
                  setRestoreError(null);
                  setRestoring(selected.revision);
                }}
              >
                <RotateCcwIcon />
                Restore revision {selected.revision}
              </Button>
            )}
          </div>
          {selected.parent === null ? (
            <p className="text-sm text-muted-foreground">
              The notes as generated. Later revisions are compared with the one before them.
            </p>
          ) : !shown || !parent ? (
            <Skeleton className="h-32 w-full" />
          ) : (
            <>
              <p className="text-sm text-muted-foreground">
                Compared with revision {selected.parent}.
              </p>
              {changes.length === 0 ? (
                <p className="text-sm text-muted-foreground">No topic text changed.</p>
              ) : (
                changes.map((change) => <TopicDiff key={change.topic_id} change={change} />)
              )}
            </>
          )}
        </section>
      )}

      <Dialog open={restoring !== null} onOpenChange={(open) => !open && !pending && setRestoring(null)}>
        <DialogContent className="max-h-[85svh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Restore revision {restoring}?</DialogTitle>
            <DialogDescription>
              {!target
                ? "Comparing it with the current revision…"
                : restored.length === 0
                  ? `Revision ${restoring} has the same topic text as the current revision ${revision}.`
                  : `A new revision after ${revision} gets the text of revision ${restoring} for ` +
                    `${restored.map((c) => c.topic_id).join(", ")}. Every revision stays in the ` +
                    "history, and restored topics need to be verified again."}
            </DialogDescription>
          </DialogHeader>
          {affectedDrafts.length > 0 && (
            <p className="text-sm text-warning">
              This tab has an unsaved draft of {affectedDrafts.join(", ")}. It is kept, and it will
              be based on an older revision afterwards.
            </p>
          )}
          {restored.map((change) => (
            <TopicDiff key={change.topic_id} change={change} />
          ))}
          {restoreError && (
            <p role="alert" className="text-sm text-destructive">
              Not restored: {restoreError}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" disabled={pending} onClick={() => setRestoring(null)}>
              Cancel
            </Button>
            <Button disabled={pending || !target || restored.length === 0} onClick={restore}>
              {pending ? <Spinner /> : <RotateCcwIcon />}
              Restore
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
