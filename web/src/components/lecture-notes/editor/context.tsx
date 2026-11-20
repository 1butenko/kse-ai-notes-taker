"use client";

import { createContext, useContext } from "react";

import type { LectureNotesSource } from "@/lib/api";

export type NotesEditorContextValue = {
  /** The notes being edited: their figures are served from their published site. */
  source: LectureNotesSource;
  /** Where a figure (`assets/x.svg`) can be shown from: a new one from memory. */
  assetUrl: (name: string) => string;
  /** Every figure the note may show: the published ones and the ones added here. */
  assetNames: string[];
  /** Add an SVG figure; returns the name it got (`assets/<name>.svg`). */
  addAsset: (fileName: string, svg: string) => string;
  /** Open the insert menu for a block (by its path), replacing it when it is empty. */
  openInsertMenu: (path: number[]) => void;
};

export const NotesEditorContext = createContext<NotesEditorContextValue | null>(null);

export function useNotesEditor(): NotesEditorContextValue {
  const value = useContext(NotesEditorContext);
  if (!value) throw new Error("useNotesEditor outside the notes editor");
  return value;
}
