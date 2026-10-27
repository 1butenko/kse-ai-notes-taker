"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CircleAlertIcon, PlusIcon } from "lucide-react";

import { CoursePage } from "@/components/course/course-page";
import { CreateCourseDialog } from "@/components/course/create-course-dialog";
import { FileViewerProvider } from "@/components/dashboard/file-viewer";
import { useMoodleCourse } from "@/components/dashboard/moodle-course-context";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, getPlan, listCourseInfo } from "@/lib/api";

const STEPS = [
  { title: "Syllabus", detail: "Add the syllabus and the books or papers students read." },
  {
    title: "Check the lectures",
    detail: "The syllabus is read into lectures. Rename, remove or add them, then approve.",
  },
  {
    title: "Notes",
    detail: "Each lecture's chapters are found in your books and its notes are written from them.",
  },
];

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "none" }
  | { kind: "course"; course: string; name: string };

/**
 * The one course, or the way to create it. A course stored before course names existed
 * (the last Moodle course, or the local one) opens as it is when it has a session plan.
 */
export function CourseHome() {
  const { imported, restoring } = useMoodleCourse();
  const [state, setState] = useState<State>({ kind: "loading" });
  const [creating, setCreating] = useState(false);
  // The Moodle course restored on page load; an import inside the dialog must not swap the page.
  const restored = useRef<typeof imported>(null);
  const started = useRef(false);

  const load = useCallback(async () => {
    const imported = restored.current;
    try {
      const [named] = await listCourseInfo();
      if (named) {
        setState({ kind: "course", course: named.course, name: named.name });
        return;
      }
      const moodleKey = imported ? String(imported.course.id) : null;
      for (const course of [moodleKey, "local"].filter((key) => key !== null)) {
        const plan = await getPlan(course).catch(() => null);
        if (plan?.transcript) {
          const name =
            course === moodleKey && imported ? imported.course.fullname : "Untitled course";
          setState({ kind: "course", course, name });
          return;
        }
      }
      setState({ kind: "none" });
    } catch (err) {
      setState({
        kind: "error",
        message:
          err instanceof ApiError ? err.message : "Couldn't reach the server. Please try again.",
      });
    }
  }, []);

  useEffect(() => {
    if (restoring || started.current) return;
    started.current = true;
    restored.current = imported;
    load();
  }, [restoring, imported, load]);

  return (
    <FileViewerProvider>
      {state.kind === "loading" && (
        <div className="flex flex-col gap-4">
          <Skeleton className="h-9 w-72" />
          <Skeleton className="h-5 w-40" />
          <Skeleton className="mt-6 h-72 w-full" />
        </div>
      )}

      {state.kind === "error" && (
        <Alert variant="destructive">
          <CircleAlertIcon />
          <AlertTitle>Couldn&apos;t load your course</AlertTitle>
          <AlertDescription className="flex flex-col items-start gap-2">
            {state.message}
            <Button size="sm" variant="outline" onClick={load}>
              Try again
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {state.kind === "none" && (
        <section
          aria-labelledby="empty-title"
          className="grid gap-10 py-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:py-16"
        >
          <div className="flex flex-col items-start gap-4">
            <h1 id="empty-title" className="text-4xl">
              Start with the course syllabus
            </h1>
            <p className="text-lg text-muted-foreground">
              Upload it with the readings it cites. The notes are written from those readings.
            </p>
            <Button size="lg" onClick={() => setCreating(true)}>
              <PlusIcon />
              Create course
            </Button>
          </div>
          <ol aria-label="How a course is set up" className="flex flex-col border-t">
            {STEPS.map((step, index) => (
              <li
                key={step.title}
                className="grid grid-cols-[3rem_minmax(0,1fr)] gap-x-3 border-b py-5"
              >
                <span className="text-2xl leading-none font-bold tabular-nums">{index + 1}</span>
                <span className="flex flex-col gap-1">
                  <span className="font-medium">{step.title}</span>
                  <span className="text-sm text-muted-foreground">{step.detail}</span>
                </span>
              </li>
            ))}
          </ol>
        </section>
      )}

      {state.kind === "course" && (
        <CoursePage
          key={state.course}
          course={state.course}
          name={state.name}
          onDeleted={() => {
            setState({ kind: "loading" });
            load();
          }}
        />
      )}

      <CreateCourseDialog
        open={creating}
        onOpenChange={setCreating}
        onCreated={(course, name) => {
          setCreating(false);
          setState({ kind: "course", course, name });
        }}
      />
    </FileViewerProvider>
  );
}
