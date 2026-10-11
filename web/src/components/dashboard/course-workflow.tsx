"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  ArrowLeftIcon,
  ArrowRightIcon,
  CheckIcon,
  CircleAlertIcon,
} from "lucide-react";
import { toast } from "sonner";

import { CoursePlan } from "@/components/dashboard/course-plan";
import { FileViewerProvider } from "@/components/dashboard/file-viewer";
import { useMoodleCourse } from "@/components/dashboard/moodle-course-context";
import { NotesStage } from "@/components/dashboard/notes-stage";
import { ReadingMaterialsUpload } from "@/components/dashboard/reading-materials-upload";
import { SyllabusStage } from "@/components/dashboard/syllabus-stage";
import { SyllabusUpload } from "@/components/dashboard/syllabus-upload";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  ApiError,
  courseKey,
  fileName,
  getPlan,
  listCourseFiles,
  uploadFiles,
  uploadMoodleFiles,
  type CourseFiles,
  type PlanView,
  type SavedFile,
} from "@/lib/api";
import { findSyllabusFiles } from "@/lib/moodle-files";

const STAGES = [
  {
    id: "upload",
    title: "Upload",
    heading: "Upload course materials",
    summary: "Add the syllabus and the books or papers students read.",
  },
  {
    id: "syllabus",
    title: "Syllabus",
    heading: "Extract the session plan",
    summary: "Pick the syllabus with the schedule and read its sessions.",
  },
  {
    id: "materials",
    title: "Materials",
    heading: "Map readings to sessions",
    summary: "Find the cited chapters in your books and approve the excerpts.",
  },
  {
    id: "notes",
    title: "Notes",
    heading: "Generate lecture notes",
    summary: "Plan the topics, write each from its readings, verify it and typeset a PDF.",
  },
] as const;

type StageId = (typeof STAGES)[number]["id"];

type Status = { kind: "idle" } | { kind: "saving" } | { kind: "error"; message: string };

const NO_FILES: CourseFiles = { syllabus: [], reading: [] };

function StageFooter({ onBack, children }: { onBack?: () => void; children?: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2">
      {onBack ? (
        <Button variant="outline" onClick={onBack}>
          <ArrowLeftIcon />
          Back
        </Button>
      ) : (
        <span />
      )}
      {children}
    </div>
  );
}

export function CourseWorkflow() {
  const { imported, restoring } = useMoodleCourse();
  const [stage, setStage] = useState<StageId | null>(null);
  const [syllabusFiles, setSyllabusFiles] = useState<File[]>([]);
  const [readingFiles, setReadingFiles] = useState<File[]>([]);
  const [hiddenMoodleIds, setHiddenMoodleIds] = useState<Set<string>>(new Set());
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [stored, setStored] = useState<CourseFiles>(NO_FILES);
  const [plan, setPlan] = useState<PlanView | null>(null);
  const [notesDone, setNotesDone] = useState(false);

  const courseId = imported?.course.id;
  const course = courseKey(courseId);

  const reloadFiles = useCallback(() => {
    listCourseFiles(course).then(setStored, () => {});
  }, [course]);

  const reloadPlan = useCallback(() => {
    getPlan(course).then(setPlan, () => {});
  }, [course]);

  useEffect(() => {
    if (restoring) return;
    let cancelled = false;
    Promise.all([
      listCourseFiles(course).catch(() => NO_FILES),
      getPlan(course).catch(() => null),
    ]).then(([files, loadedPlan]) => {
      if (cancelled) return;
      setStored(files);
      setPlan(loadedPlan);
      setStage(
        loadedPlan?.transcript ? "materials" : files.syllabus.length > 0 ? "syllabus" : "upload",
      );
    });
    return () => {
      cancelled = true;
    };
  }, [restoring, course]);

  const savedSyllabusNames = new Set(stored.syllabus.map((file) => fileName(file.path)));
  const syllabusMoodleFiles = (imported ? findSyllabusFiles(imported.sections) : []).filter(
    (file) => !hiddenMoodleIds.has(file.id) && !savedSyllabusNames.has(file.saveAs),
  );
  const pendingSyllabus = syllabusFiles.length + syllabusMoodleFiles.length;
  const pending = pendingSyllabus + readingFiles.length;

  const done: Record<StageId, boolean> = {
    upload: stored.syllabus.length > 0,
    syllabus: Boolean(plan?.transcript),
    materials: Boolean(plan?.mapped),
    notes: notesDone,
  };
  const reachable = (id: StageId) =>
    STAGES.slice(
      0,
      STAGES.findIndex((s) => s.id === id),
    ).every((s) => done[s.id]);
  const current =
    stage === null ? null : reachable(stage) ? stage : STAGES.findLast((s) => reachable(s.id))!.id;

  const edit =
    <T,>(setter: (value: T) => void) =>
    (value: T) => {
      setter(value);
      setStatus({ kind: "idle" });
    };

  const hideMoodleFile = (id: string) => {
    setHiddenMoodleIds((prev) => new Set(prev).add(id));
    setStatus({ kind: "idle" });
  };

  const saveAndContinue = async () => {
    if (pending === 0) {
      setStage("syllabus");
      return;
    }
    setStatus({ kind: "saving" });
    try {
      const saved: SavedFile[] = [];
      if (syllabusMoodleFiles.length > 0) {
        const refs = syllabusMoodleFiles.map((f) => ({
          fileurl: f.fileurl,
          filename: f.saveAs,
        }));
        saved.push(...(await uploadMoodleFiles("syllabus", refs, courseId)));
      }
      if (syllabusFiles.length > 0) {
        saved.push(...(await uploadFiles("syllabus", syllabusFiles, courseId)));
      }
      if (readingFiles.length > 0) {
        saved.push(...(await uploadFiles("reading", readingFiles, courseId)));
      }
      setSyllabusFiles([]);
      setReadingFiles([]);
      setStatus({ kind: "idle" });
      toast.success("Files saved successfully", {
        description: `${saved.length} ${saved.length === 1 ? "file" : "files"} uploaded to storage.`,
      });
      const files = await listCourseFiles(course).catch(() => null);
      if (files) setStored(files);
      if (pendingSyllabus > 0 || stored.syllabus.length > 0) setStage("syllabus");
    } catch (err) {
      setStatus({
        kind: "error",
        message:
          err instanceof ApiError ? err.message : "Couldn't reach the server. Please try again.",
      });
    }
  };

  if (current === null) {
    return (
      <div className="flex flex-col gap-6">
        <div className="flex flex-col gap-2">
          <Skeleton className="h-8 w-72" />
          <Skeleton className="h-5 w-96 max-w-full" />
        </div>
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }

  const active = STAGES.find((s) => s.id === current)!;

  return (
    <FileViewerProvider>
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">{active.heading}</h1>
        <p className="text-muted-foreground">{active.summary}</p>
      </header>

      <Tabs value={current} onValueChange={(value) => setStage(value as StageId)} className="gap-6">
        <TabsList
          variant="line"
          className="grid w-full grid-cols-2 gap-2 group-data-horizontal/tabs:h-auto sm:grid-cols-4"
        >
          {STAGES.map((s, index) => (
            <TabsTrigger
              key={s.id}
              value={s.id}
              disabled={!reachable(s.id)}
              className="h-auto justify-start gap-2 px-2 py-2 after:bg-primary"
            >
              <Badge
                variant={done[s.id] || s.id === current ? "default" : "secondary"}
                className="size-6 rounded-full p-0"
              >
                {done[s.id] ? <CheckIcon /> : index + 1}
              </Badge>
              {s.title}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="upload" className="flex flex-col gap-6">
          <div className="grid gap-6 lg:grid-cols-2 lg:items-start">
            <SyllabusUpload
              files={syllabusFiles}
              onFilesChange={edit(setSyllabusFiles)}
              moodleFiles={syllabusMoodleFiles}
              onRemoveMoodleFile={hideMoodleFile}
              savedFiles={stored.syllabus}
            />
            <ReadingMaterialsUpload
              files={readingFiles}
              onFilesChange={edit(setReadingFiles)}
              savedFiles={stored.reading}
            />
          </div>

          {status.kind === "error" && (
            <Alert variant="destructive">
              <CircleAlertIcon />
              <AlertTitle>Couldn&apos;t save the files</AlertTitle>
              <AlertDescription>{status.message}</AlertDescription>
            </Alert>
          )}

          <StageFooter>
            <Button
              onClick={saveAndContinue}
              disabled={status.kind === "saving" || (pending === 0 && !done.upload)}
            >
              {status.kind === "saving"
                ? "Saving…"
                : pending > 0
                  ? "Save and continue"
                  : "Continue"}
              <ArrowRightIcon />
            </Button>
          </StageFooter>
        </TabsContent>

        <TabsContent value="syllabus" className="flex flex-col gap-6">
          <SyllabusStage
            files={stored.syllabus}
            plan={plan}
            onPlan={setPlan}
            onReload={reloadPlan}
            onDeleted={() => {
              reloadFiles();
              reloadPlan();
            }}
          />
          <StageFooter onBack={() => setStage("upload")}>
            <Button disabled={!done.syllabus} onClick={() => setStage("materials")}>
              Continue
              <ArrowRightIcon />
            </Button>
          </StageFooter>
        </TabsContent>

        <TabsContent value="materials" className="flex flex-col gap-6">
          {plan?.transcript && (
            <Card>
              <CardHeader>
                <CardTitle>Course plan</CardTitle>
              </CardHeader>
              <CardContent>
                <CoursePlan
                  plan={plan}
                  courseId={courseId}
                  readingFiles={stored.reading}
                  onPlan={setPlan}
                  onUploaded={reloadFiles}
                />
              </CardContent>
            </Card>
          )}
          <StageFooter onBack={() => setStage("syllabus")}>
            <Button disabled={!done.materials} onClick={() => setStage("notes")}>
              Continue
              <ArrowRightIcon />
            </Button>
          </StageFooter>
        </TabsContent>

        <TabsContent value="notes" className="flex flex-col gap-6">
          <NotesStage
            course={course}
            hasMaterials={Boolean(plan?.sessions.some((s) => s.files.length > 0))}
            onDoneChange={setNotesDone}
          />
          <StageFooter onBack={() => setStage("materials")} />
        </TabsContent>
      </Tabs>
    </FileViewerProvider>
  );
}
