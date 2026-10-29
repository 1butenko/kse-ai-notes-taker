"use client";

import { useState } from "react";
import {
  CheckCheckIcon,
  EyeIcon,
  FileTextIcon,
  InboxIcon,
  ScissorsIcon,
  WandSparklesIcon,
  XIcon,
} from "lucide-react";
import { toast } from "sonner";

import { AddMaterialDialog } from "@/components/dashboard/add-material-dialog";
import { useFileViewer } from "@/components/dashboard/file-viewer";
import { BooksPanel, EXACT_METHODS, SessionProposals } from "@/components/dashboard/mapping-parts";
import { SessionBlock, TranscriptNotes } from "@/components/dashboard/transcript-parts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemMedia,
  ItemTitle,
} from "@/components/ui/item";
import {
  ApiError,
  approveAllProposals,
  detachFile,
  dismissUnassigned,
  fileName,
  mapMaterials,
  type FileView,
  type PlanView,
  type SavedFile,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type CoursePlanProps = {
  plan: PlanView;
  courseId?: number;
  readingFiles: SavedFile[];
  onPlan: (plan: PlanView) => void;
  onUploaded: () => void;
};

export function FileRow({
  file,
  label,
  onRemove,
}: {
  file: FileView;
  label: string;
  onRemove: () => void;
}) {
  const openFile = useFileViewer();
  const excerpt = file.excerpt;
  const name = excerpt ? excerpt.label : fileName(file.path);
  return (
    <Item
      variant="outline"
      size="sm"
      className={cn(excerpt && "border-success/50 bg-success/5")}
    >
      <ItemMedia variant="icon" className={cn(excerpt && "text-success")}>
        {excerpt ? <ScissorsIcon /> : <FileTextIcon />}
      </ItemMedia>
      <ItemContent className="min-w-0">
        <ItemTitle className="block w-full truncate" title={name}>
          {name}
        </ItemTitle>
        {excerpt && (
          <ItemDescription className="truncate">
            {excerpt.printed ?? `PDF pp. ${excerpt.pdf_start}–${excerpt.pdf_end}`} of{" "}
            {fileName(excerpt.book)}
          </ItemDescription>
        )}
      </ItemContent>
      <ItemActions>
        {excerpt && <Badge className="bg-success/15 text-success">Cropped</Badge>}
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={`Open ${name}`}
          onClick={() => openFile({ path: file.path, title: name })}
        >
          <EyeIcon />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={`${excerpt ? "Delete" : label} ${name}`}
          onClick={onRemove}
        >
          <XIcon />
        </Button>
      </ItemActions>
    </Item>
  );
}

export function CoursePlan({ plan, courseId, readingFiles, onPlan, onUploaded }: CoursePlanProps) {
  const [busy, setBusy] = useState(false);
  const [mapping, setMapping] = useState(false);
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

  const map = async () => {
    setMapping(true);
    try {
      const next = await mapMaterials(plan.course);
      onPlan(next);
      const count = next.sessions
        .flatMap((s) => s.proposals)
        .filter((p) => p.status === "proposed").length;
      toast.success("Materials mapped", {
        description: `${count} ${count === 1 ? "excerpt" : "excerpts"} to review.`,
      });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't reach the server.");
    } finally {
      setMapping(false);
    }
  };

  const exact = plan.sessions
    .flatMap((s) => s.proposals)
    .filter(
      (p) => p.status === "proposed" && EXACT_METHODS.includes(p.method) && p.pdf_start !== null,
    );

  return (
    <div className="flex flex-col gap-4">
      <TranscriptNotes transcript={transcript} />

      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={map} disabled={mapping || busy}>
          <WandSparklesIcon />
          {mapping
            ? "Mapping… (up to a minute)"
            : plan.mapped
              ? "Map materials again"
              : "Map materials"}
        </Button>
        {exact.length > 0 && (
          <Button
            variant="outline"
            disabled={busy || mapping}
            onClick={() => update(() => approveAllProposals(plan.course))}
          >
            <CheckCheckIcon />
            Approve all exact ({exact.length})
          </Button>
        )}
      </div>

      {plan.mapped && <BooksPanel plan={plan} readingFiles={readingFiles} update={update} />}

      {plan.unassigned.length > 0 && (
        <div className="flex flex-col gap-2 rounded-lg border border-dashed p-3">
          <div className="flex items-center gap-2 font-medium">
            <InboxIcon className="size-4" />
            Unassigned
          </div>
          <p className="text-sm text-muted-foreground">
            These files were attached to sessions that are no longer in the syllabus. Add them to a
            session with <span className="font-medium">Add material → Choose existing</span>.
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
            <SessionBlock
              key={entry.id}
              session={entry.session}
              materials={transcript.learning_materials}
            >
              <SessionProposals proposals={entry.proposals} course={plan.course} update={update} />
              <span className="text-xs font-medium text-muted-foreground">Files</span>
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
