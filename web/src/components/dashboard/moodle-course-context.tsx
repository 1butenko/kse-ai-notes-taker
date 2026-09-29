"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { ApiError, getCourse, getCourseContents, type Course, type Section } from "@/lib/api";

type ImportedCourse = {
  course: Course;
  sections: Section[];
};

type MoodleCourseContextValue = {
  imported: ImportedCourse | null;
  setImported: (imported: ImportedCourse) => void;
  /** True while the last opened course is being re-imported after a page load. */
  restoring: boolean;
};

const MoodleCourseContext = createContext<MoodleCourseContextValue | null>(null);

const LAST_COURSE_KEY = "lastMoodleCourseId";

function readLastCourseId(): number | null {
  try {
    const value = Number(localStorage.getItem(LAST_COURSE_KEY));
    return Number.isInteger(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

function writeLastCourseId(id: number | null) {
  try {
    if (id === null) localStorage.removeItem(LAST_COURSE_KEY);
    else localStorage.setItem(LAST_COURSE_KEY, String(id));
  } catch {
    // Storage unavailable (private mode, blocked): the course just isn't remembered.
  }
}

export function MoodleCourseProvider({ children }: { children: ReactNode }) {
  const [imported, setImportedState] = useState<ImportedCourse | null>(null);
  const [restoring, setRestoring] = useState(true);

  useEffect(() => {
    const id = readLastCourseId();
    const restore =
      id === null ? Promise.resolve(null) : Promise.all([getCourse(id), getCourseContents(id)]);
    restore
      .then((result) => {
        if (result) setImportedState({ course: result[0], sections: result[1] });
      })
      .catch((err) => {
        // Forget a course Moodle rejects; keep it when the server is just unreachable.
        if (err instanceof ApiError) writeLastCourseId(null);
      })
      .finally(() => setRestoring(false));
  }, []);

  const setImported = (value: ImportedCourse) => {
    writeLastCourseId(value.course.id);
    setImportedState(value);
  };

  return (
    <MoodleCourseContext.Provider value={{ imported, setImported, restoring }}>
      {children}
    </MoodleCourseContext.Provider>
  );
}

export function useMoodleCourse() {
  const value = useContext(MoodleCourseContext);
  if (!value) throw new Error("useMoodleCourse must be used inside MoodleCourseProvider");
  return value;
}
