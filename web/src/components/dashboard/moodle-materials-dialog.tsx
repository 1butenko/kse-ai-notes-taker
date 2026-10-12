"use client";

import { useState } from "react";
import { DownloadIcon } from "lucide-react";

import { MoodleCourseForm } from "@/components/dashboard/moodle-course-form";
import { useMoodleCourse } from "@/components/dashboard/moodle-course-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
  FieldTitle,
} from "@/components/ui/field";
import { formatSize } from "@/lib/format";
import type { MoodleSectionFiles } from "@/lib/moodle-files";

type MoodleMaterialsDialogProps = {
  sections: MoodleSectionFiles[] | null;
  selected: Set<string>;
  saved: Set<string>;
  onSelect: (ids: Set<string>) => void;
};

export function MoodleMaterialsDialog({
  sections,
  selected,
  saved,
  onSelect,
}: MoodleMaterialsDialogProps) {
  const { imported } = useMoodleCourse();
  const [open, setOpen] = useState(false);
  const [changing, setChanging] = useState(false);
  const [checked, setChecked] = useState<Set<string>>(new Set());

  const choosing = sections === null || changing;
  const available = (sections ?? []).flatMap((s) => s.files).filter((f) => !saved.has(f.saveAs));
  const allChecked = available.length > 0 && available.every((f) => checked.has(f.id));

  const toggle = (id: string, on: boolean) =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        onClick={() => {
          setChecked(new Set(selected));
          setChanging(false);
          setOpen(true);
        }}
      >
        <DownloadIcon />
        From Moodle
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="flex max-h-[85vh] flex-col sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>Import materials from Moodle</DialogTitle>
            <DialogDescription>
              {choosing ? (
                "Import a Moodle course, then pick the files and web pages to add."
              ) : (
                <>
                  {imported?.course.fullname} ·{" "}
                  <Button
                    variant="link"
                    className="h-auto p-0"
                    onClick={() => setChanging(true)}
                  >
                    Change course
                  </Button>
                </>
              )}
            </DialogDescription>
          </DialogHeader>

          {choosing ? (
            <MoodleCourseForm
              onImported={() => {
                setChecked(new Set());
                onSelect(new Set());
                setChanging(false);
              }}
              cancel={
                changing && (
                  <Button type="button" variant="outline" onClick={() => setChanging(false)}>
                    Cancel
                  </Button>
                )
              }
            />
          ) : sections.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              This Moodle course has no files or web page links besides the syllabus.
            </p>
          ) : (
            <div className="-mx-1 flex min-h-0 flex-col gap-6 overflow-y-auto px-1">
              <Field orientation="horizontal">
                <Checkbox
                  id="moodle-all"
                  checked={allChecked}
                  disabled={available.length === 0}
                  onCheckedChange={(on) =>
                    setChecked(on ? new Set(available.map((f) => f.id)) : new Set())
                  }
                />
                <FieldLabel htmlFor="moodle-all">Select all</FieldLabel>
              </Field>
              {sections.map((section, i) => (
                <FieldSet key={i}>
                  <FieldLegend variant="label">{section.title}</FieldLegend>
                  <FieldGroup className="gap-2">
                    {section.files.map((file) => {
                      const isSaved = saved.has(file.saveAs);
                      const id = `moodle-${file.id}`;
                      return (
                        <FieldLabel key={file.id} htmlFor={id}>
                          <Field orientation="horizontal" data-disabled={isSaved}>
                            <Checkbox
                              id={id}
                              checked={isSaved || checked.has(file.id)}
                              disabled={isSaved}
                              onCheckedChange={(on) => toggle(file.id, on)}
                            />
                            <FieldContent className="min-w-0">
                              <FieldTitle className="block w-full truncate" title={file.name}>
                                {file.name}
                              </FieldTitle>
                              <FieldDescription className="truncate" title={file.filename}>
                                {file.filename}
                                {file.size > 0 && ` · ${formatSize(file.size)}`}
                              </FieldDescription>
                            </FieldContent>
                            {isSaved ? (
                              <Badge variant="outline">Saved</Badge>
                            ) : (
                              file.kind === "link" && <Badge variant="secondary">Web page</Badge>
                            )}
                          </Field>
                        </FieldLabel>
                      );
                    })}
                  </FieldGroup>
                </FieldSet>
              ))}
            </div>
          )}

          {!choosing && (
            <DialogFooter>
              <p className="mr-auto text-sm text-muted-foreground">
                Downloaded when you save. Web pages are saved as text; videos are skipped.
              </p>
              <Button
                disabled={checked.size === 0 && selected.size === 0}
                onClick={() => {
                  onSelect(checked);
                  setOpen(false);
                }}
              >
                {checked.size > 0
                  ? `Add ${checked.size} ${checked.size === 1 ? "file" : "files"}`
                  : "Clear selection"}
              </Button>
            </DialogFooter>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
