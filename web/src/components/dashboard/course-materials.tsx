"use client";

import { useState } from "react";
import { ArrowRightIcon, CircleAlertIcon } from "lucide-react";
import { toast } from "sonner";

import { useMoodleCourse } from "@/components/dashboard/moodle-course-context";
import { ReadingMaterialsUpload } from "@/components/dashboard/reading-materials-upload";
import { SyllabusUpload } from "@/components/dashboard/syllabus-upload";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ApiError, uploadFiles, uploadMoodleFiles, type SavedFile } from "@/lib/api";
import { findSyllabusFiles } from "@/lib/moodle-files";

type Status =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "error"; message: string };

export function CourseMaterials() {
  const { imported } = useMoodleCourse();
  const [syllabusFiles, setSyllabusFiles] = useState<File[]>([]);
  const [readingFiles, setReadingFiles] = useState<File[]>([]);
  const [hiddenMoodleIds, setHiddenMoodleIds] = useState<Set<string>>(new Set());
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  const courseId = imported?.course.id;
  const syllabusMoodleFiles = (imported ? findSyllabusFiles(imported.sections) : []).filter(
    (file) => !hiddenMoodleIds.has(file.id),
  );
  const total = syllabusFiles.length + readingFiles.length + syllabusMoodleFiles.length;

  const edit = <T,>(setter: (value: T) => void) => (value: T) => {
    setter(value);
    setStatus({ kind: "idle" });
  };

  const hideMoodleFile = (id: string) => {
    setHiddenMoodleIds((prev) => new Set(prev).add(id));
    setStatus({ kind: "idle" });
  };

  const onContinue = async () => {
    setStatus({ kind: "saving" });
    try {
      const saved: SavedFile[] = [];
      if (syllabusMoodleFiles.length > 0) {
        const refs = syllabusMoodleFiles.map((f) => ({ fileurl: f.fileurl, filename: f.saveAs }));
        saved.push(...(await uploadMoodleFiles("syllabus", refs, courseId)));
      }
      if (syllabusFiles.length > 0) {
        saved.push(...(await uploadFiles("syllabus", syllabusFiles, courseId)));
      }
      if (readingFiles.length > 0) {
        saved.push(...(await uploadFiles("reading", readingFiles, courseId)));
      }
      setStatus({ kind: "idle" });
      toast.success("Files saved successfully", {
        description: `${saved.length} ${saved.length === 1 ? "file" : "files"} uploaded to storage.`,
      });
    } catch (err) {
      setStatus({
        kind: "error",
        message:
          err instanceof ApiError ? err.message : "Couldn't reach the server. Please try again.",
      });
    }
  };

  return (
    <>
      <div className="grid gap-6 lg:grid-cols-2 lg:items-start">
        <SyllabusUpload
          files={syllabusFiles}
          onFilesChange={edit(setSyllabusFiles)}
          moodleFiles={syllabusMoodleFiles}
          onRemoveMoodleFile={hideMoodleFile}
        />
        <ReadingMaterialsUpload files={readingFiles} onFilesChange={edit(setReadingFiles)} />
      </div>

      {status.kind === "error" && (
        <Alert variant="destructive">
          <CircleAlertIcon />
          <AlertTitle>Couldn&apos;t save the files</AlertTitle>
          <AlertDescription>{status.message}</AlertDescription>
        </Alert>
      )}

      <div className="flex justify-end">
        <Button onClick={onContinue} disabled={total === 0 || status.kind === "saving"}>
          {status.kind === "saving" ? "Saving…" : "Continue"}
          <ArrowRightIcon />
        </Button>
      </div>
    </>
  );
}
