"use client";

import { useState } from "react";
import { CircleAlertIcon, EyeIcon, PlusIcon, Trash2Icon } from "lucide-react";

import { autoMatch } from "@/components/course/auto-match";
import { useFileViewer } from "@/components/dashboard/file-viewer";
import { TranscriptNotes } from "@/components/dashboard/transcript-parts";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import {
  ApiError,
  fileName,
  saveTranscript,
  type PlanView,
  type Session,
  type Transcript,
} from "@/lib/api";

type SetupReviewProps = {
  course: string;
  transcript: Transcript;
  syllabusPath: string;
  onPlan: (plan: PlanView) => void;
  onApproved: () => void;
};

function newSession(index: number): Session {
  return {
    label: `Session ${index + 1}`,
    number: null,
    date: null,
    topic: "",
    subtopics: [],
    required_readings: [],
    optional_readings: [],
  };
}

function errorMessage(err: unknown) {
  return err instanceof ApiError ? err.message : "Couldn't reach the server. Please try again.";
}

/** The syllabus read into lectures: rename, remove or add, then approve to match the readings. */
export function SetupReview({
  course,
  transcript,
  syllabusPath,
  onPlan,
  onApproved,
}: SetupReviewProps) {
  const openFile = useFileViewer();
  const [sessions, setSessions] = useState(transcript.sessions);
  const [dirty, setDirty] = useState(false);
  const [step, setStep] = useState<"idle" | "saving" | "matching">("idle");
  const [error, setError] = useState<string | null>(null);

  const edit = (index: number, patch: Partial<Session>) => {
    setSessions((prev) => prev.map((s, i) => (i === index ? { ...s, ...patch } : s)));
    setDirty(true);
  };

  const remove = (index: number) => {
    setSessions((prev) => prev.filter((_, i) => i !== index));
    setDirty(true);
  };

  const add = () => {
    setSessions((prev) => [...prev, newSession(prev.length)]);
    setDirty(true);
  };

  const valid = sessions.length > 0 && sessions.every((s) => s.label.trim());

  const approve = async () => {
    setError(null);
    try {
      if (dirty) {
        setStep("saving");
        await saveTranscript(syllabusPath, { ...transcript, sessions });
        setDirty(false);
      }
      setStep("matching");
      onPlan(await autoMatch(course));
      onApproved();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setStep("idle");
    }
  };

  const busy = step !== "idle";

  return (
    <section aria-labelledby="review-title" className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h2 id="review-title" className="text-xl">
            Check the lectures
          </h2>
          <p className="text-muted-foreground">
            Read from{" "}
            <button
              type="button"
              className="inline-flex items-center gap-1 underline underline-offset-4 hover:text-foreground"
              onClick={() => openFile({ path: syllabusPath })}
            >
              {fileName(syllabusPath)}
              <EyeIcon className="size-3.5" aria-hidden="true" />
            </button>
            . Rename, remove or add lectures, then approve.
          </p>
        </div>
        <Button size="lg" disabled={!valid || busy} onClick={approve}>
          {busy && <Spinner />}
          {step === "saving"
            ? "Saving…"
            : step === "matching"
              ? "Matching readings…"
              : "Approve and match readings"}
        </Button>
      </div>

      <TranscriptNotes transcript={transcript} />

      {step === "matching" && (
        <p role="status" className="text-sm text-muted-foreground">
          Finding each lecture&apos;s chapters in your readings. This takes up to a minute.
        </p>
      )}
      {error && (
        <Alert variant="destructive">
          <CircleAlertIcon />
          <AlertTitle>Couldn&apos;t match the readings</AlertTitle>
          <AlertDescription className="flex flex-col items-start gap-2">
            {error}
            <Button size="sm" variant="outline" onClick={approve}>
              Retry
            </Button>
          </AlertDescription>
        </Alert>
      )}

      <ol aria-label="Lectures" className="flex flex-col border-t">
        {sessions.map((session, index) => (
          <li
            key={index}
            className="grid grid-cols-[2.5rem_minmax(0,1fr)_auto] items-start gap-x-3 gap-y-2 border-b py-3 sm:grid-cols-[2.5rem_minmax(0,12rem)_minmax(0,1fr)_auto]"
          >
            <span className="col-start-1 row-start-1 pt-1.5 text-lg font-bold tabular-nums text-muted-foreground">
              {index + 1}
            </span>
            <Input
              className="col-start-2 row-start-1"
              aria-label={`Lecture ${index + 1} label`}
              value={session.label}
              disabled={busy}
              onChange={(event) => edit(index, { label: event.target.value })}
            />
            <div className="col-start-2 row-start-2 flex min-w-0 flex-col gap-1 sm:col-start-3 sm:row-start-1">
              <textarea
                aria-label={`Lecture ${index + 1} topic`}
                placeholder="Topic"
                rows={1}
                value={session.topic}
                disabled={busy}
                onChange={(event) => edit(index, { topic: event.target.value })}
                className="min-h-8 w-full resize-none rounded-lg border border-input bg-transparent px-2.5 py-1 text-base transition-colors outline-none [field-sizing:content] placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 md:text-sm"
              />
              {(session.date || session.subtopics.length > 0) && (
                <p className="px-1 text-sm text-muted-foreground">
                  {[session.date, session.subtopics.join(", ")].filter(Boolean).join(". ")}
                </p>
              )}
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="col-start-3 row-start-1 sm:col-start-4"
              aria-label={`Remove lecture ${index + 1}`}
              disabled={busy}
              onClick={() => remove(index)}
            >
              <Trash2Icon />
            </Button>
          </li>
        ))}
      </ol>
      {sessions.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No lectures left. Add one, or read the syllabus again from the course menu.
        </p>
      )}
      <div>
        <Button variant="outline" disabled={busy} onClick={add}>
          <PlusIcon />
          Add a lecture
        </Button>
      </div>
    </section>
  );
}
