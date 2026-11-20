"use client";

import dynamic from "next/dynamic";

import { Spinner } from "@/components/ui/spinner";

/** The editor and Plate load only on the edit page, and only in the browser. */
export const NotesEditorLoader = dynamic(
  () => import("./notes-editor").then((m) => m.NotesEditor),
  {
    ssr: false,
    loading: () => (
      <div className="flex flex-1 items-center justify-center p-12">
        <Spinner className="size-6 text-muted-foreground" />
      </div>
    ),
  },
);
