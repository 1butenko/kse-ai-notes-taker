"use client";

import { useState } from "react";
import { ImageIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { ApiError, uploadNoteAsset } from "@/lib/api";

const MAX_BYTES = 10 * 1024 * 1024;
// The figure syntax the server accepts (app/note_assets.py IMAGE).
const LABEL = /^fig-[a-zA-Z0-9][a-zA-Z0-9_.-]*$/;

/** Every `{#fig-…}` label in some Markdown. */
export function figureLabels(markdown: string): string[] {
  return [...markdown.matchAll(/\{#(fig-[^{}\s]+)\}/g)].map((match) => match[1]);
}

/** `fig-<topic>-<n>`, the first one not taken in the document or the draft. */
export function nextFigureLabel(topic: string, taken: Set<string>): string {
  const stem = `fig-${topic.toLowerCase().replace(/[^a-z0-9_.-]+/g, "-")}`;
  let n = 1;
  while (taken.has(`${stem}-${n}`)) n++;
  return `${stem}-${n}`;
}

type FigureDialogProps = {
  course: string;
  run: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  block: string;
  defaultLabel: string;
  taken: Set<string>;
  onInsert: (markdown: string) => void;
};

/**
 * Imports an image and puts its figure Markdown into the local draft; nothing is saved.
 * Mount it per use: its fields start from `defaultLabel` each time.
 */
export function FigureDialog({
  course,
  run,
  open,
  onOpenChange,
  block,
  defaultLabel,
  taken,
  onInsert,
}: FigureDialogProps) {
  const [file, setFile] = useState<File | null>(null);
  const [caption, setCaption] = useState("");
  const [label, setLabel] = useState(defaultLabel);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const trimmed = caption.trim();
  const problem = !file
    ? "Choose a PNG or JPEG image."
    : file.size > MAX_BYTES
      ? "Image exceeds 10 MiB."
      : !trimmed
        ? "Add a caption."
        : /[[\]\n]/.test(trimmed)
          ? "A caption can't contain square brackets or line breaks."
          : !LABEL.test(label)
            ? "A label starts with fig- and uses letters, digits, '.', '_' or '-'."
            : taken.has(label)
              ? `${label} is already used in these notes.`
              : null;

  const insert = async () => {
    if (!file || problem) return;
    setUploading(true);
    setError(null);
    try {
      const uploaded = await uploadNoteAsset(course, run, file);
      onInsert(`![${trimmed}](${uploaded.markdown_path}){#${label}}`);
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't reach the server. Please try again.");
    } finally {
      setUploading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Insert an image into {block}</DialogTitle>
          <DialogDescription>
            The image is uploaded to this run, and its figure goes into your draft. Nothing is
            saved until you save the topic; the image appears in the notes after that.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          <Label htmlFor="figure-file">Image (PNG or JPEG, up to 10 MiB)</Label>
          <Input
            id="figure-file"
            type="file"
            accept="image/png,image/jpeg"
            onChange={(event) => {
              setError(null);
              setFile(event.target.files?.[0] ?? null);
            }}
          />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="figure-caption">Caption</Label>
          <Input
            id="figure-caption"
            value={caption}
            onChange={(event) => setCaption(event.target.value)}
          />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="figure-label">Label</Label>
          <Input
            id="figure-label"
            value={label}
            onChange={(event) => setLabel(event.target.value.trim())}
            className="font-mono"
          />
          <p className="text-xs text-muted-foreground">
            Refer to it in the text as @{LABEL.test(label) ? label : "fig-…"}.
          </p>
        </div>
        {(error || (file && problem)) && (
          <p role="alert" className="text-sm text-destructive">
            {error ?? problem}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={!!problem || uploading} onClick={insert}>
            {uploading ? <Spinner /> : <ImageIcon />}
            Upload and insert
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
