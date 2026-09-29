"use client";

import { useState } from "react";
import { FileTextIcon, InboxIcon, XIcon } from "lucide-react";
import { toast } from "sonner";

import { AddMaterialDialog } from "@/components/dashboard/add-material-dialog";
import {
  CourseMaterialsList,
  SessionBlock,
  TranscriptNotes,
} from "@/components/dashboard/transcript-parts";
import { Button } from "@/components/ui/button";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemGroup,
  ItemMedia,
  ItemTitle,
} from "@/components/ui/item";
import {
  ApiError,
  detachFile,
  dismissUnassigned,
  fileName,
  type PlanView,
  type SavedFile,
} from "@/lib/api";

type CoursePlanProps = {
  plan: PlanView;
  courseId?: number;
  readingFiles: SavedFile[];
  onPlan: (plan: PlanView) => void;
  onUploaded: () => void;
};

function FileRow({ file, label, onRemove }: { file: SavedFile; label: string; onRemove: () => void }) {
  const name = fileName(file.path);
  return (
    <Item variant="outline" size="sm">
      <ItemMedia variant="icon">
        <FileTextIcon />
      </ItemMedia>
      <ItemContent className="min-w-0">
        <ItemTitle className="block w-full truncate" title={name}>
          {name}
        </ItemTitle>
      </ItemContent>
      <ItemActions>
        <Button variant="ghost" size="icon-sm" aria-label={`${label} ${name}`} onClick={onRemove}>
          <XIcon />
        </Button>
      </ItemActions>
    </Item>
  );
}

export function CoursePlan({ plan, courseId, readingFiles, onPlan, onUploaded }: CoursePlanProps) {
  const [busy, setBusy] = useState(false);
  const transcript = plan.transcript;
  if (!transcript) return null;

  const update = async (action: () => Promise<PlanView>) => {
    if (busy) return;
    setBusy(true);
    try {
      onPlan(await action());
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't reach the server.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <TranscriptNotes transcript={transcript} />
      <CourseMaterialsList transcript={transcript} />

      {plan.unassigned.length > 0 && (
        <div className="flex flex-col gap-2 rounded-lg border border-dashed p-3">
          <div className="flex items-center gap-2 font-medium">
            <InboxIcon className="size-4" />
            Unassigned
          </div>
          <p className="text-sm text-muted-foreground">
            These files were attached to sessions that are no longer in the syllabus. Add them to
            a session with <span className="font-medium">Add material → Choose existing</span>.
          </p>
          <ItemGroup className="gap-2">
            {plan.unassigned.map((file) => (
              <FileRow
                key={file.path}
                file={file}
                label="Dismiss"
                onRemove={() => update(() => dismissUnassigned(plan.course, file.path))}
              />
            ))}
          </ItemGroup>
        </div>
      )}

      {plan.sessions.length > 0 ? (
        <ol className="flex flex-col gap-2">
          {plan.sessions.map((entry) => (
            <SessionBlock key={entry.id} session={entry.session}>
              <span className="text-xs font-semibold uppercase text-muted-foreground">Files</span>
              {entry.files.length > 0 && (
                <ItemGroup className="gap-2">
                  {entry.files.map((file) => (
                    <FileRow
                      key={file.path}
                      file={file}
                      label="Detach"
                      onRemove={() => update(() => detachFile(plan.course, entry.id, file.path))}
                    />
                  ))}
                </ItemGroup>
              )}
              <AddMaterialDialog
                course={plan.course}
                courseId={courseId}
                entry={entry}
                readingFiles={readingFiles}
                onPlan={onPlan}
                onUploaded={onUploaded}
              />
            </SessionBlock>
          ))}
        </ol>
      ) : (
        <p className="text-sm text-muted-foreground">No session plan found.</p>
      )}
    </div>
  );
}
