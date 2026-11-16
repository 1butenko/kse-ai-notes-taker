"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeftIcon, CircleAlertIcon } from "lucide-react";

import { CoursePage } from "@/components/course/course-page";
import { FileViewerProvider } from "@/components/dashboard/file-viewer";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, getCourseInfo } from "@/lib/api";

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string; missing: boolean }
  | { kind: "ready"; name: string };

async function fetchCourse(course: string): Promise<State> {
  try {
    return { kind: "ready", name: (await getCourseInfo(course)).name };
  } catch (err) {
    return {
      kind: "error",
      missing: err instanceof ApiError && err.status === 404,
      message:
        err instanceof ApiError ? err.message : "Couldn't reach the server. Please try again.",
    };
  }
}

/** One of the teacher's courses, by its key. */
export function CourseView({ course }: { course: string }) {
  const router = useRouter();
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    fetchCourse(course).then(setState);
  }, [course]);

  const retry = () => {
    setState({ kind: "loading" });
    fetchCourse(course).then(setState);
  };

  return (
    <FileViewerProvider>
      <div className="flex flex-col gap-6">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 self-start text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
        >
          <ArrowLeftIcon className="size-4" aria-hidden="true" />
          Your courses
        </Link>

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
            <AlertTitle>
              {state.missing ? "Course not found" : "Couldn't load this course"}
            </AlertTitle>
            <AlertDescription className="flex flex-col items-start gap-2">
              {state.missing ? "It isn't one of your courses." : state.message}
              {!state.missing && (
                <Button size="sm" variant="outline" onClick={retry}>
                  Try again
                </Button>
              )}
            </AlertDescription>
          </Alert>
        )}

        {state.kind === "ready" && (
          <CoursePage course={course} name={state.name} onDeleted={() => router.push("/")} />
        )}
      </div>
    </FileViewerProvider>
  );
}
