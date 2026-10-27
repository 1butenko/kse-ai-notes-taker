"use client";

import { useState } from "react";
import { CircleAlertIcon, DownloadIcon } from "lucide-react";

import { useMoodleCourse } from "@/components/dashboard/moodle-course-context";
import { MoodleCourseForm } from "@/components/dashboard/moodle-course-form";
import { ReadingMaterialsUpload } from "@/components/dashboard/reading-materials-upload";
import { SyllabusUpload } from "@/components/dashboard/syllabus-upload";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  ApiError,
  courseKey,
  saveCourseInfo,
  uploadFiles,
  uploadMoodleFiles,
  uploadMoodleLinks,
} from "@/lib/api";
import { findMaterialFiles, findSyllabusFiles } from "@/lib/moodle-files";

type CreateCourseDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (course: string, name: string) => void;
};

export function CreateCourseDialog({ open, onOpenChange, onCreated }: CreateCourseDialogProps) {
  const { imported } = useMoodleCourse();
  const [name, setName] = useState("");
  const [moodleOpen, setMoodleOpen] = useState(false);
  const [syllabusFiles, setSyllabusFiles] = useState<File[]>([]);
  const [readingFiles, setReadingFiles] = useState<File[]>([]);
  const [hiddenMoodleIds, setHiddenMoodleIds] = useState<Set<string>>(new Set());
  const [readingMoodleIds, setReadingMoodleIds] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A Moodle import fills an empty name with the course's own.
  const [namedFrom, setNamedFrom] = useState<number | null>(null);
  if (imported && imported.course.id !== namedFrom) {
    setNamedFrom(imported.course.id);
    if (!name.trim()) setName(imported.course.fullname);
  }

  const courseId = imported?.course.id;
  const syllabusMoodleFiles = (imported ? findSyllabusFiles(imported.sections) : []).filter(
    (file) => !hiddenMoodleIds.has(file.id),
  );
  const materialSections = imported ? findMaterialFiles(imported.sections) : null;
  const readingMoodleFiles = (materialSections ?? [])
    .flatMap((section) => section.files)
    .filter((file) => readingMoodleIds.has(file.id));
  const syllabusCount = syllabusFiles.length + syllabusMoodleFiles.length;
  const ready = name.trim().length > 0 && syllabusCount === 1;

  const create = async () => {
    setSaving(true);
    setError(null);
    const course = courseKey(courseId);
    try {
      // The name first: a course whose upload fails still opens and asks for its syllabus.
      const info = await saveCourseInfo(course, name.trim());
      if (syllabusMoodleFiles.length > 0) {
        const refs = syllabusMoodleFiles.map((f) => ({ fileurl: f.fileurl, filename: f.saveAs }));
        await uploadMoodleFiles("syllabus", refs, courseId);
      }
      if (syllabusFiles.length > 0) await uploadFiles("syllabus", syllabusFiles, courseId);
      const moodleFiles = readingMoodleFiles.filter((f) => f.kind === "file");
      const moodleLinks = readingMoodleFiles.filter((f) => f.kind === "link");
      if (moodleFiles.length > 0) {
        const refs = moodleFiles.map((f) => ({ fileurl: f.fileurl, filename: f.saveAs }));
        await uploadMoodleFiles("reading", refs, courseId);
      }
      if (moodleLinks.length > 0 && courseId) {
        await uploadMoodleLinks(courseId, moodleLinks.map((f) => f.moduleId));
      }
      if (readingFiles.length > 0) await uploadFiles("reading", readingFiles, courseId);
      onCreated(info.course, info.name);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't reach the server. Please try again.",
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !saving && onOpenChange(next)}>
      <DialogContent className="flex max-h-[90svh] flex-col gap-6 overflow-y-auto sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>Create a course</DialogTitle>
          <DialogDescription>
            Add its syllabus and readings. The syllabus is read into lectures for you to check.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <Field>
            <FieldLabel htmlFor="course-name">Course name</FieldLabel>
            <Input
              id="course-name"
              name="course-name"
              autoComplete="off"
              placeholder="Linear Algebra"
              value={name}
              onChange={(event) => setName(event.target.value)}
              autoFocus
            />
          </Field>
          {moodleOpen ? (
            <div className="rounded-lg bg-muted p-4">
              <MoodleCourseForm
                onImported={() => setMoodleOpen(false)}
                cancel={
                  <Button type="button" variant="outline" onClick={() => setMoodleOpen(false)}>
                    Cancel
                  </Button>
                }
              />
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2 text-sm">
              {imported ? (
                <span className="text-muted-foreground">
                  From Moodle: <span className="text-foreground">{imported.course.fullname}</span>
                </span>
              ) : (
                <span className="text-muted-foreground">Teaching this course on Moodle?</span>
              )}
              <Button type="button" variant="outline" size="sm" onClick={() => setMoodleOpen(true)}>
                <DownloadIcon />
                {imported ? "Change Moodle course" : "Import from Moodle"}
              </Button>
            </div>
          )}
        </div>

        <div className="grid gap-4 lg:grid-cols-2 lg:items-start">
          <div className="flex flex-col gap-2">
            <SyllabusUpload
              files={syllabusFiles}
              onFilesChange={setSyllabusFiles}
              moodleFiles={syllabusMoodleFiles}
              onRemoveMoodleFile={(id) => setHiddenMoodleIds((prev) => new Set(prev).add(id))}
              savedFiles={[]}
            />
            {syllabusCount > 1 && (
              <FieldDescription className="text-warning">
                Keep one syllabus file: remove the others.
              </FieldDescription>
            )}
          </div>
          <ReadingMaterialsUpload
            files={readingFiles}
            onFilesChange={setReadingFiles}
            savedFiles={[]}
            moodleSections={materialSections}
            moodleFiles={readingMoodleFiles}
            selectedMoodleIds={readingMoodleIds}
            onSelectMoodleFiles={setReadingMoodleIds}
          />
        </div>

        {error && (
          <Alert variant="destructive">
            <CircleAlertIcon />
            <AlertTitle>Couldn&apos;t create the course</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <DialogFooter>
          <Button type="button" variant="outline" disabled={saving} onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="button" disabled={!ready || saving} onClick={create}>
            {saving ? "Creating…" : "Create course"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
