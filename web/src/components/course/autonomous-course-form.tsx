"use client";

import { useState } from "react";
import { CircleAlertIcon, SparklesIcon } from "lucide-react";

import { useMoodleCourse } from "@/components/dashboard/moodle-course-context";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import {
  ApiError,
  courseKey,
  getCourse,
  getCourseContents,
  saveCourseInfo,
  uploadMoodleFiles,
  uploadMoodleLinks,
} from "@/lib/api";
import { findMaterialFiles, findSyllabusFiles } from "@/lib/moodle-files";

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

export function AutonomousCourseForm({
  onCreated,
  onBusyChange,
  cancel,
}: AutonomousCourseFormProps) {
  const { setImported } = useMoodleCourse();
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
    setStep("Reading the course from Moodle…");
    try {
      const [course, sections] = await Promise.all([
        getCourse(courseId),
        getCourseContents(courseId),
      ]);

      const syllabus = findSyllabusFiles(sections)[0];
      if (!syllabus) {
        setError(
          "No syllabus file found in this Moodle course. Switch to Manual to upload one yourself.",
        );
        return;
      }

      setStep("Creating the course…");
      const info = await saveCourseInfo(
        courseKey(courseId),
        course.fullname.trim(),
      );

      setStep("Importing the syllabus…");
      await uploadMoodleFiles(
        "syllabus",
        [{ fileurl: syllabus.fileurl, filename: syllabus.saveAs }],
        courseId,
      );

      const readings = findMaterialFiles(sections).flatMap(
        (section) => section.files,
      );
      const files = readings.filter((f) => f.kind === "file");
      const links = readings.filter((f) => f.kind === "link");
      if (readings.length > 0) {
        setStep(
          `Importing ${readings.length} reading${readings.length === 1 ? "" : "s"}…`,
        );
      }
      if (files.length > 0) {
        await uploadMoodleFiles(
          "reading",
          files.map((f) => ({ fileurl: f.fileurl, filename: f.saveAs })),
          courseId,
        );
      }
      if (links.length > 0)
        await uploadMoodleLinks(
          courseId,
          links.map((f) => f.moduleId),
        );

      setImported({ course, sections });
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
          That&apos;s all we need. The name, syllabus and readings are imported
          from Moodle for you.
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
