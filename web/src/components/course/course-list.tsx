"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { BookOpenIcon, ChevronRightIcon, CircleAlertIcon, PlusIcon } from "lucide-react";

import { CreateCourseDialog } from "@/components/course/create-course-dialog";
import { RoleBadge } from "@/components/course/team-panel";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemTitle,
} from "@/components/ui/item";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, type CourseListItem, listCourseInfo } from "@/lib/api";

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; courses: CourseListItem[] };

async function fetchCourses(): Promise<State> {
  try {
    return { kind: "ready", courses: await listCourseInfo() };
  } catch (err) {
    return {
      kind: "error",
      message:
        err instanceof ApiError ? err.message : "Couldn't reach the server. Please try again.",
    };
  }
}

const created = new Intl.DateTimeFormat("en-GB", { dateStyle: "medium" });

export function coursePath(course: string): string {
  return `/courses/${encodeURIComponent(course)}`;
}

/** The signed-in teacher's courses, and the way to create one. */
export function CourseList() {
  const router = useRouter();
  const [state, setState] = useState<State>({ kind: "loading" });
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    fetchCourses().then(setState);
  }, []);

  const retry = () => {
    setState({ kind: "loading" });
    fetchCourses().then(setState);
  };

  const hasCourses = state.kind === "ready" && state.courses.length > 0;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-3xl">Your courses</h1>
        {hasCourses && (
          <Button onClick={() => setCreating(true)}>
            <PlusIcon data-icon="inline-start" />
            Create course
          </Button>
        )}
      </div>

      {state.kind === "loading" && (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      )}

      {state.kind === "error" && (
        <Alert variant="destructive">
          <CircleAlertIcon />
          <AlertTitle>Couldn&apos;t load your courses</AlertTitle>
          <AlertDescription className="flex flex-col items-start gap-2">
            {state.message}
            <Button size="sm" variant="outline" onClick={retry}>
              Try again
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {state.kind === "ready" && state.courses.length === 0 && (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <BookOpenIcon />
            </EmptyMedia>
            <EmptyTitle>No courses yet</EmptyTitle>
            <EmptyDescription>
              Create a course from Moodle. Its syllabus and readings become lecture notes.
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button onClick={() => setCreating(true)}>
              <PlusIcon data-icon="inline-start" />
              Create course
            </Button>
          </EmptyContent>
        </Empty>
      )}

      {hasCourses && (
        <ItemGroup className="gap-3">
          {state.courses.map((course) => (
            <Item
              key={course.course}
              variant="outline"
              render={<Link href={coursePath(course.course)} />}
            >
              <ItemContent>
                <ItemTitle>{course.name}</ItemTitle>
                <ItemDescription>
                  Created {created.format(new Date(course.created_at))}
                </ItemDescription>
              </ItemContent>
              <ItemActions>
                <RoleBadge role={course.role} />
                <ChevronRightIcon className="text-muted-foreground" />
              </ItemActions>
            </Item>
          ))}
        </ItemGroup>
      )}

      <CreateCourseDialog
        open={creating}
        onOpenChange={setCreating}
        onCreated={(course) => {
          setCreating(false);
          router.push(coursePath(course));
        }}
      />
    </div>
  );
}
