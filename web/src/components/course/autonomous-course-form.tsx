"use client";

import { useState } from "react";
import { CircleAlertIcon, SparklesIcon } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import {
  ApiError,
  courseKey,
  getCourse,
  saveCourseInfo,
  startAgentSync,
} from "@/lib/api";

/** The Moodle course ID from a course link (`.../course/view.php?id=4510`) or a bare number. */
export function parseMoodleCourseId(input: string): number | null {
  const text = input.trim();
  if (/^\d+$/.test(text)) return Number(text);
  try {
    const id = new URL(text).searchParams.get("id");
    return id && /^\d+$/.test(id) ? Number(id) : null;
  } catch {
    return null;
  }
}

type AutonomousCourseFormProps = {
  onCreated: (course: string, name: string) => void;
  /** Reports whether a create is running, so the dialog can't be closed mid-way. */
  onBusyChange: (busy: boolean) => void;
  cancel: React.ReactNode;
};

/**
 * Creates the course from its Moodle link and hands it to the AI Note Taker, which gathers the
 * syllabus and readings, reads the lectures and attaches the readings on the course page.
 */
export function AutonomousCourseForm({
  onCreated,
  onBusyChange,
  cancel,
}: AutonomousCourseFormProps) {
  const [link, setLink] = useState("");
  const [step, setStep] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const courseId = parseMoodleCourseId(link);
  const pending = step !== null;
  const showInvalid = link.trim().length > 0 && courseId === null;

  const run = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (courseId === null) return;
    setError(null);
    onBusyChange(true);
    setStep("Finding the course…");
    try {
      const course = await getCourse(courseId);
      setStep("Creating the course…");
      const info = await saveCourseInfo(
        courseKey(courseId),
        course.fullname.trim(),
      );
      setStep("Starting the AI Note Taker…");
      await startAgentSync(info.course);
      onCreated(info.course, info.name);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Couldn't reach the server. Please try again.",
      );
    } finally {
      setStep(null);
      onBusyChange(false);
    }
  };

  return (
    <form onSubmit={run} className="flex flex-col gap-6">
      <Field data-invalid={showInvalid ? true : undefined}>
        <FieldLabel htmlFor="moodle-course-link">Moodle course link</FieldLabel>
        <Input
          id="moodle-course-link"
          autoComplete="off"
          placeholder="https://moodle.example.edu/course/view.php?id=4510"
          value={link}
          onChange={(event) => setLink(event.target.value)}
          disabled={pending}
          aria-invalid={showInvalid ? true : undefined}
          autoFocus
        />
        <FieldDescription>
          That&apos;s all we need. The AI Note Taker gathers the syllabus and
          readings from Moodle, reads the lectures and attaches each one&apos;s
          readings.
        </FieldDescription>
      </Field>

      {error && (
        <Alert variant="destructive">
          <CircleAlertIcon />
          <AlertTitle>Couldn&apos;t create the course</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="flex justify-end gap-2">
        {cancel}
        <Button type="submit" disabled={courseId === null || pending}>
          {pending ? <Spinner /> : <SparklesIcon />}
          {step ?? "Create course"}
        </Button>
      </div>
    </form>
  );
}
