"use client";

import { useState, type ReactNode } from "react";
import { DownloadIcon } from "lucide-react";

import { useMoodleCourse } from "@/components/dashboard/moodle-course-context";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { ApiError, getCourse, getCourseContents } from "@/lib/api";

type MoodleCourseFormProps = {
  onImported: () => void;
  cancel?: ReactNode;
};

export function MoodleCourseForm({ onImported, cancel }: MoodleCourseFormProps) {
  const { setImported } = useMoodleCourse();
  const [courseId, setCourseId] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isValid = /^\d+$/.test(courseId.trim());

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const id = Number(courseId.trim());
      const course = await getCourse(id);
      const sections = await getCourseContents(id);
      setImported({ course, sections });
      setCourseId("");
      onImported();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't reach the server. Please try again.",
      );
    } finally {
      setPending(false);
    }
  };

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-6">
      <Field data-invalid={error ? true : undefined}>
        <FieldLabel htmlFor="moodle-course-id">Moodle course ID</FieldLabel>
        <Input
          id="moodle-course-id"
          inputMode="numeric"
          autoComplete="off"
          placeholder="e.g. 4510"
          value={courseId}
          onChange={(event) => setCourseId(event.target.value)}
          aria-invalid={error ? true : undefined}
          autoFocus
        />
        {error ? (
          <FieldError>{error}</FieldError>
        ) : (
          <FieldDescription>
            The number after <code>id=</code> in the course URL. Its syllabus is added to the
            Syllabus card.
          </FieldDescription>
        )}
      </Field>
      <div className="flex justify-end gap-2">
        {cancel}
        <Button type="submit" disabled={!isValid || pending}>
          <DownloadIcon />
          {pending ? "Importing…" : "Import course"}
        </Button>
      </div>
    </form>
  );
}
