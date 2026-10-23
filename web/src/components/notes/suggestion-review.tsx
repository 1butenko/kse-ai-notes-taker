"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckIcon, CircleAlertIcon, ShieldCheckIcon, SparklesIcon, XIcon } from "lucide-react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import {
  ApiError,
  applyNotesSuggestion,
  createNotesSuggestion,
  getNotesSuggestion,
  getVerificationJob,
  rejectNotesSuggestion,
  verifyNotesTopic,
  type NoteSuggestion,
  type TopicNote,
  type Verification,
  type VerificationIssue,
  type VerificationJob,
} from "@/lib/api";

import { diffTopic, hasChanges } from "./diff";
import { TopicDiff } from "./revision-diff";

const PRESETS = [
  "Explain this more simply",
  "Expand the example with a worked case",
  "Clarify the proof step by step",
];
const POLL_MS = 800;

function errorMessage(err: unknown) {
  return err instanceof ApiError ? err.message : "Couldn't reach the server. Please try again.";
}

/** Polls `read` until `done` says the record has settled. */
function usePolled<T extends { id: string }>(
  id: string | null,
  read: (id: string) => Promise<T>,
  done: (value: T) => boolean,
  onSettled: (value: T) => void,
) {
  const [value, setValue] = useState<T | null>(null);
  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const next = await read(id);
        if (cancelled) return;
        setValue(next);
        if (done(next)) {
          onSettled(next);
          return;
        }
      } catch {
        // A temporary failure keeps what is shown; polling continues.
      }
      if (!cancelled) timer = setTimeout(poll, POLL_MS);
    };
    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // The callbacks are stable by construction in the caller.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);
  // A previous record never shows under a new id while the first answer is on its way.
  return id && value?.id === id ? value : null;
}

/** Whether the check itself found nothing wrong, whatever else blocks "verified". */
function checkIsClean(check: Verification) {
  return check.passed && !check.escalate && !check.issues.some((issue) => issue.severity === "major");
}

/** The check's major issues, then the topic's standing gaps that block verification. */
function Issues({ check, blocking }: { check: Verification; blocking: VerificationIssue[] }) {
  const issues = [...check.issues.filter((issue) => issue.severity === "major"), ...blocking];
  return (
    <ul aria-label="Verification issues" className="flex flex-col gap-2 text-sm">
      {issues.map((issue, index) => (
        <li key={index} className="rounded-md border border-warning/40 p-2">
          <p className="font-medium break-words">
            {issue.block === null ? "Whole topic" : `Block ${issue.block + 1}`} · {issue.kind}
          </p>
          <p className="break-words">{issue.detail}</p>
          <p className="text-xs break-words text-muted-foreground">Suggested fix: {issue.fix}</p>
        </li>
      ))}
      {check.escalate && issues.length === 0 && (
        <li className="rounded-md border border-warning/40 p-2">
          The verifier could not confidently check this text
          {check.escalation_reason ? `: ${check.escalation_reason}` : "."}
        </li>
      )}
    </ul>
  );
}

function Outcome({ verified, check }: { verified: boolean; check: Verification | null }) {
  if (!check) return <Badge variant="outline">Not checked</Badge>;
  return verified ? (
    <Badge className="bg-success/10 text-success">Verified against the sources</Badge>
  ) : (
    <Badge className="bg-warning/15 text-warning">Not verified</Badge>
  );
}

type ReviewProps = {
  suggestion: NoteSuggestion;
  topic: TopicNote;
  /** HEAD as the page last loaded it. */
  revision: number;
  busy: boolean;
  onApply: () => void;
  onReject: () => void;
};

/** A prepared suggestion with its text, source and verification differences. */
export function SuggestionReview({ suggestion, topic, revision, busy, onApply, onReject }: ReviewProps) {
  const outdated = suggestion.base_revision !== revision;
  const change = diffTopic(topic, { ...topic, blocks: suggestion.proposed_blocks });
  const check = suggestion.verification;
  return (
    <section aria-label="Suggestion review" className="flex min-w-0 flex-col gap-3 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-sm font-medium">Suggestion for {suggestion.topic_id}</h4>
        <span className="text-xs text-muted-foreground">based on revision {suggestion.base_revision}</span>
        <Outcome verified={suggestion.verified} check={check} />
      </div>
      <p className="text-xs break-words text-muted-foreground">
        Request: {suggestion.instruction}
        {suggestion.block_ids.length > 0
          ? ` · blocks ${suggestion.block_ids.join(", ")}`
          : " · whole topic"}
      </p>
      {outdated && (
        <Alert className="border-warning/40">
          <CircleAlertIcon className="text-warning" />
          <AlertTitle>The notes changed after this suggestion</AlertTitle>
          <AlertDescription>
            The suggestion is for revision {suggestion.base_revision}, but the notes are now at
            revision {revision}. It can&apos;t be applied; reject it and ask again.
          </AlertDescription>
        </Alert>
      )}
      {hasChanges(change) ? (
        <TopicDiff change={change} showTitle={false} />
      ) : (
        <p className="text-sm text-muted-foreground">The suggestion doesn&apos;t change any text.</p>
      )}
      {check && (
        <div className="flex flex-col gap-2">
          <p className="text-sm font-medium">
            {suggestion.verified
              ? "A fresh check of this exact text found no problems."
              : checkIsClean(check)
                ? "A fresh check of this exact text found no new problems, but a standing gap keeps the topic from being verified."
                : "A fresh check of this exact text did not verify it."}
          </p>
          {!suggestion.verified && <Issues check={check} blocking={suggestion.blocking} />}
          {!suggestion.verified && (
            <p className="text-xs text-muted-foreground">
              If you apply it, the topic stays Unresolved and these issues stay visible.
            </p>
          )}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <Button disabled={busy || outdated} onClick={onApply}>
          {busy ? <Spinner /> : <CheckIcon />}
          Apply suggestion
        </Button>
        <Button variant="outline" disabled={busy} onClick={onReject}>
          <XIcon />
          Reject suggestion
        </Button>
      </div>
    </section>
  );
}

type AssistProps = {
  course: string;
  run: string;
  /** HEAD: the saved text revision. */
  revision: number;
  topic: TopicNote;
  /** Suggestions and checks work from saved text, so an unsaved draft pauses them. */
  hasDraft: boolean;
  refresh: () => Promise<unknown>;
};

/** Targeted AI suggestions for some blocks of a topic, and a manual recheck. */
export function AiAssist({ course, run, revision, topic, hasDraft, refresh }: AssistProps) {
  const [selected, setSelected] = useState<string[]>([]);
  const [instruction, setInstruction] = useState("");
  const [suggestionId, setSuggestionId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const topicId = topic.topic_id;

  const readSuggestion = useCallback((id: string) => getNotesSuggestion(course, run, id), [course, run]);
  const suggestion = usePolled(
    suggestionId,
    readSuggestion,
    (value) => !["queued", "running"].includes(value.status),
    () => {},
  );
  const settledJob = useCallback(
    (job: VerificationJob) => {
      if (job.revision !== null) {
        toast.success(`Verification recorded as revision ${job.revision}`);
        refresh();
      }
    },
    [refresh],
  );
  const readJob = useCallback((id: string) => getVerificationJob(course, run, id), [course, run]);
  const job = usePolled(jobId, readJob, (value) => ["done", "failed"].includes(value.status), settledJob);

  // Another topic or a new run starts clean; a suggestion for a different topic never shows.
  const shown = suggestion && suggestion.topic_id === topicId ? suggestion : null;
  const waiting = shown && ["queued", "running"].includes(shown.status);
  const checking = job && ["queued", "running"].includes(job.status);

  const ask = async () => {
    setStarting(true);
    setError(null);
    try {
      const created = await createNotesSuggestion(course, run, {
        base_revision: revision,
        topic_id: topicId,
        block_ids: selected,
        instruction: instruction.trim(),
      });
      setSuggestionId(created.id);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setStarting(false);
    }
  };

  const apply = async () => {
    if (!shown) return;
    setBusy(true);
    setError(null);
    try {
      const result = await applyNotesSuggestion(course, run, shown.id, shown.base_revision);
      toast.success(`Applied as revision ${result.revision.revision}`);
      setSuggestionId(null);
      setSelected([]);
      setInstruction("");
      await refresh();
    } catch (err) {
      // The notes moved on: show the current revision, and never apply the old result.
      if (err instanceof ApiError && err.status === 409) await refresh();
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const reject = async () => {
    if (!shown) return;
    setBusy(true);
    setError(null);
    try {
      await rejectNotesSuggestion(course, run, shown.id);
      toast.info("Suggestion rejected. The notes are unchanged.");
      setSuggestionId(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const verify = async () => {
    setError(null);
    try {
      const started = await verifyNotesTopic(course, run, topicId, revision);
      setJobId(started.id);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const toggle = (id: string, on: boolean) =>
    setSelected((prev) => (on ? [...prev.filter((x) => x !== id), id] : prev.filter((x) => x !== id)));
  const canAsk = !hasDraft && !starting && !waiting && instruction.trim().length > 0;
  const noBlocks = topic.blocks.length === 0 || topic.evidence.length === 0;

  return (
    <section aria-label="AI suggestions" className="flex min-w-0 flex-col gap-3 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <SparklesIcon className="size-4" />
        <h3 className="text-sm font-medium">AI suggestions and checks</h3>
      </div>
      <p className="text-xs text-muted-foreground">
        The model proposes changes to the blocks you pick, using this topic&apos;s sources only.
        Nothing changes until you apply a suggestion. Editing and rendering never need the model.
      </p>
      {hasDraft && (
        <p className="text-xs text-warning">
          Suggestions and checks use the saved text (revision {revision}). Save or discard your
          draft first.
        </p>
      )}
      {error && (
        <Alert variant="destructive">
          <CircleAlertIcon />
          <AlertTitle>Not done</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {!shown || shown.status === "failed" || shown.status === "rejected" || shown.status === "applied" ? (
        <div className="flex flex-col gap-3">
          {shown?.status === "failed" && (
            <Alert variant="destructive">
              <CircleAlertIcon />
              <AlertTitle>No suggestion was made</AlertTitle>
              <AlertDescription>{shown.error ?? "The request failed."} The notes are unchanged.</AlertDescription>
            </Alert>
          )}
          <fieldset className="flex flex-col gap-1.5" disabled={hasDraft || noBlocks}>
            <legend className="mb-1.5 text-sm font-medium">Blocks to change</legend>
            {topic.blocks.map((block, index) => (
              <label key={block.id} className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  className="mt-0.5 size-4 accent-primary"
                  checked={selected.includes(block.id)}
                  aria-label={`Select block ${index + 1} (${block.id})`}
                  onChange={(event) => toggle(block.id, event.target.checked)}
                />
                <span className="min-w-0 break-words">
                  Block {index + 1} · {block.kind}
                  {block.title ? ` · ${block.title}` : ""}
                </span>
              </label>
            ))}
            <p className="text-xs text-muted-foreground">
              {selected.length === 0 ? "No block picked: the whole topic is in scope." : `${selected.length} picked.`}
            </p>
          </fieldset>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`suggest-${topicId}`}>Instruction</Label>
            <div className="flex flex-wrap gap-1.5">
              {PRESETS.map((preset) => (
                <Button
                  key={preset}
                  size="xs"
                  variant="outline"
                  disabled={hasDraft}
                  onClick={() => setInstruction(preset)}
                >
                  {preset}
                </Button>
              ))}
            </div>
            <textarea
              id={`suggest-${topicId}`}
              value={instruction}
              maxLength={2000}
              disabled={hasDraft}
              onChange={(event) => setInstruction(event.target.value)}
              className="min-h-16 w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button disabled={!canAsk || noBlocks} onClick={ask}>
              {starting ? <Spinner /> : <SparklesIcon />}
              Request suggestion
            </Button>
            <Button variant="outline" disabled={hasDraft || !!checking || noBlocks} onClick={verify}>
              {checking ? <Spinner /> : <ShieldCheckIcon />}
              Verify this topic again
            </Button>
          </div>
        </div>
      ) : waiting ? (
        <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner />
          Preparing a suggestion for revision {shown.base_revision}. The notes are not changed.
        </p>
      ) : (
        <SuggestionReview
          suggestion={shown}
          topic={topic}
          revision={revision}
          busy={busy}
          onApply={apply}
          onReject={reject}
        />
      )}

      {checking && (
        <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner />
          Checking the saved text of {topicId} against its sources.
        </p>
      )}
      {job?.status === "failed" && (
        <Alert variant="destructive">
          <CircleAlertIcon />
          <AlertTitle>The check did not finish</AlertTitle>
          <AlertDescription>{job.error ?? "The check failed."} The notes are unchanged.</AlertDescription>
        </Alert>
      )}
      {job?.status === "done" && job.topic_id === topicId && (
        <div aria-label="Verification result" role="group" className="flex flex-col gap-2 text-sm">
          {job.conflict ? (
            <Alert className="border-warning/40">
              <CircleAlertIcon className="text-warning" />
              <AlertTitle>The notes changed during the check</AlertTitle>
              <AlertDescription>
                {job.error ?? "The result was not recorded."} Verify the topic again.
              </AlertDescription>
            </Alert>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <Outcome verified={job.verified} check={job.verification} />
                <span>
                  Recorded as revision {job.revision}.{" "}
                  {job.verified ? "" : "The topic stays Unresolved with these issues."}
                </span>
              </div>
              {!job.verified && job.verification && (
                <Issues check={job.verification} blocking={job.blocking} />
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}
