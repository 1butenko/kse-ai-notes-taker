"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { endTabSession, type Course, type Section } from "@/lib/api";

type ImportedCourse = {
  course: Course;
  sections: Section[];
};

type MoodleCourseContextValue = {
  imported: ImportedCourse | null;
  setImported: (imported: ImportedCourse) => void;
};

const MoodleCourseContext = createContext<MoodleCourseContextValue | null>(null);

export function MoodleCourseProvider({ children }: { children: ReactNode }) {
  const [imported, setImported] = useState<ImportedCourse | null>(null);

  useEffect(() => {
    window.addEventListener("pagehide", endTabSession);
    return () => window.removeEventListener("pagehide", endTabSession);
  }, []);

  return (
    <MoodleCourseContext.Provider value={{ imported, setImported }}>
      {children}
    </MoodleCourseContext.Provider>
  );
}

export function useMoodleCourse() {
  const value = useContext(MoodleCourseContext);
  if (!value) throw new Error("useMoodleCourse must be used inside MoodleCourseProvider");
  return value;
}
