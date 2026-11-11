"use client";

import { useState } from "react";

import { AutonomousCourseForm } from "@/components/course/autonomous-course-form";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

type CreateCourseDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (course: string, name: string) => void;
};

/** A course starts from its Moodle link; the AI Note Taker sets up the rest. */
export function CreateCourseDialog({
  open,
  onOpenChange,
  onCreated,
}: CreateCourseDialogProps) {
  const [busy, setBusy] = useState(false);

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent className="flex max-h-[90svh] flex-col gap-6 overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Create course environment</DialogTitle>
        </DialogHeader>
        <AutonomousCourseForm
          onCreated={onCreated}
          onBusyChange={setBusy}
          cancel={
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
          }
        />
      </DialogContent>
    </Dialog>
  );
}
