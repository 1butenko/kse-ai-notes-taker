"use client";

import { useState } from "react";
import { DownloadIcon } from "lucide-react";

import { useMoodleCourse } from "@/components/dashboard/moodle-course-context";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { SidebarMenuButton } from "@/components/ui/sidebar";
import { ApiError, getCourse, getCourseContents } from "@/lib/api";

export function MoodleImportDialog() {
  const { setImported } = useMoodleCourse();
  const [open, setOpen] = useState(false);
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
      setOpen(false);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't reach the server. Please try again.",
      );
    } finally {
      setPending(false);
    }
  };

  return (
    <>
      <SidebarMenuButton tooltip="Import from Moodle" onClick={() => setOpen(true)}>
        <DownloadIcon />
        <span>Import from Moodle</span>
      </SidebarMenuButton>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <form onSubmit={onSubmit} className="flex flex-col gap-6">
            <DialogHeader>
              <DialogTitle>Import from Moodle</DialogTitle>
              <DialogDescription>
                Enter the Moodle course ID to import its materials.
              </DialogDescription>
            </DialogHeader>

            <Field data-invalid={error ? true : undefined}>
              <FieldLabel htmlFor="moodle-course-id">Course ID</FieldLabel>
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
              {error && <FieldError>{error}</FieldError>}
            </Field>

            <DialogFooter>
              <DialogClose render={<Button type="button" variant="outline" />}>
                Cancel
              </DialogClose>
              <Button type="submit" disabled={!isValid || pending}>
                <DownloadIcon />
                {pending ? "Importing…" : "Import"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
