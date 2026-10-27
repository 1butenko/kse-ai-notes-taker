"use client";

import { useRef, useState } from "react";
import { UploadIcon } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { ApiError, uploadLectureFiles, type PlanView } from "@/lib/api";
import { cn } from "@/lib/utils";

// What a note can be written from: PDF, Word and plain-text formats.
const ACCEPT = ".pdf,.docx,.md,.txt,.tex,.qmd";

type LectureFilesDropProps = {
  course: string;
  sessionId: string;
  onPlan: (plan: PlanView) => void;
};

/** Drop zone for files of this lecture only: never course readings, never matched elsewhere. */
export function LectureFilesDrop({ course, sessionId, onPlan }: LectureFilesDropProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [uploading, setUploading] = useState(false);

  const upload = async (files: File[]) => {
    if (files.length === 0 || uploading) return;
    setUploading(true);
    try {
      onPlan(await uploadLectureFiles(course, sessionId, files));
      toast.success(files.length === 1 ? "File added to this lecture" : "Files added to this lecture");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't reach the server.");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div
      role="group"
      aria-label="Add files for this lecture only"
      aria-busy={uploading}
      onDragOver={(event) => {
        event.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => {
        event.preventDefault();
        setOver(false);
        upload(Array.from(event.dataTransfer.files));
      }}
      className={cn(
        "flex flex-col items-center gap-2 rounded-lg border border-dashed px-4 py-6 text-center transition-colors",
        over && "border-ring bg-muted",
      )}
    >
      <p className="text-sm font-medium">Drop slides, handouts or your own notes here</p>
      <p className="max-w-sm text-sm text-muted-foreground">
        Used for this lecture&apos;s note only. They are not course readings and no other lecture
        sees them.
      </p>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPT}
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
        onChange={(event) => {
          upload(Array.from(event.target.files ?? []));
          event.target.value = "";
        }}
      />
      <Button
        variant="outline"
        size="sm"
        disabled={uploading}
        onClick={() => inputRef.current?.click()}
      >
        {uploading ? <Spinner /> : <UploadIcon />}
        {uploading ? "Uploading…" : "Choose files"}
      </Button>
    </div>
  );
}
