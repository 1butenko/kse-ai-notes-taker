"use client";

import { useRef, useState } from "react";
import {
  CircleAlertIcon,
  GitCompareIcon,
  PlusIcon,
  SaveIcon,
  ShieldAlertIcon,
  TriangleAlertIcon,
  Undo2Icon,
} from "lucide-react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import {
  ApiError,
  getNotesRevision,
  saveNotesTopic,
  type NotesDocument,
  type RevisionView,
  type TopicNote,
} from "@/lib/api";

import { BlockEditor } from "./block-editor";
import { diffTopic, hasChanges } from "./diff";
import {
  currentDraft,
  discardDraft,
  draftBlocks,
  patchBlocks,
  sameBlocks,
  writeDraft,
  type DraftBlock,
  type TopicDraft,
} from "./draft";
import { FigureDialog, figureLabels, nextFigureLabel } from "./figure-dialog";
import { TopicDiff } from "./revision-diff";
import { AiAssist } from "./suggestion-review";

const LANGUAGES = [
  { value: "uk", label: "Ukrainian (uk)" },
  { value: "en", label: "English (en)" },
];

function errorMessage(err: unknown) {
  return err instanceof ApiError ? err.message : "Couldn't reach the server. Please try again.";
}

function newKey() {
  return `new-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

type TopicEditorProps = {
  course: string;
  run: string;
  /** HEAD: the current revision, its document and this topic in it. */
  revision: number;
  document: NotesDocument;
  topic: TopicNote;
  draft: TopicDraft | null;
  /** Reloads the run's current revision; the draft is never touched by it. */
  refresh: () => Promise<unknown>;
};

/**
 * A Markdown/LaTeX block editor for one topic. Changes live in this tab's sessionStorage
 * under the revision they started from until they are saved or explicitly discarded.
 */
export function TopicEditor({ course, run, revision, document, topic, draft, refresh }: TopicEditorProps) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [persisted, setPersisted] = useState(true);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [figureFor, setFigureFor] = useState<string | null>(null);
  const [since, setSince] = useState<RevisionView | null>(null);
  const [loadingSince, setLoadingSince] = useState(false);
  const carets = useRef(new Map<string, number>());

  const topicId = topic.topic_id;
  const saved = draftBlocks(topic);
  const working: TopicDraft = draft ?? {
    base_revision: revision,
    blocks: saved,
    language: null,
    updated_at: "",
  };
  const needsLanguage = document.language === null;
  const stale = draft !== null && draft.base_revision < revision;

  const commit = (next: TopicDraft) => {
    const clean =
      next.base_revision === revision &&
      sameBlocks(next.blocks, saved) &&
      !(needsLanguage && next.language);
    if (clean) {
      discardDraft(course, run, topicId);
      setPersisted(true);
    } else {
      setPersisted(writeDraft(course, run, topicId, next));
    }
  };

  const update = (change: Partial<Pick<TopicDraft, "blocks" | "language">>) =>
    commit({ ...working, ...change, updated_at: new Date().toISOString() });

  const setBlocks = (edit: (blocks: DraftBlock[]) => DraftBlock[]) =>
    update({ blocks: edit([...working.blocks]) });

  const addBlock = (at: number) =>
    setBlocks((blocks) => {
      blocks.splice(at, 0, {
        id: "",
        key: newKey(),
        kind: "explanation",
        title: null,
        content: "",
        citations: [],
      });
      return blocks;
    });

  const moveBlock = (index: number, delta: -1 | 1) =>
    setBlocks((blocks) => {
      const [block] = blocks.splice(index, 1);
      blocks.splice(index + delta, 0, block);
      return blocks;
    });

  const insertFigure = (key: string, markdown: string) =>
    setBlocks((blocks) =>
      blocks.map((block) => {
        if (block.key !== key) return block;
        const at = Math.min(carets.current.get(key) ?? block.content.length, block.content.length);
        const before = block.content.slice(0, at).replace(/\s+$/, "");
        const after = block.content.slice(at).replace(/^\s+/, "");
        return { ...block, content: [before, markdown, after].filter(Boolean).join("\n\n") };
      }),
    );

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    setError(null);
    try {
      const result = await saveNotesTopic(course, run, topicId, {
        base_revision: draft.base_revision,
        blocks: patchBlocks(draft.blocks),
        ...(needsLanguage && draft.language ? { language: draft.language } : {}),
      });
      await refresh();
      // Edits typed while the request was in flight stay as a draft on the old base.
      if (currentDraft(course, run, topicId)?.updated_at === draft.updated_at) {
        discardDraft(course, run, topicId);
      }
      const number = result.revision.revision;
      if (number === draft.base_revision) {
        toast.info(`Nothing to save: revision ${number} already has this text`);
      } else {
        toast.success(`Saved as revision ${number}`);
      }
    } catch (err) {
      // A stale base: show the current revision; the draft stays as it is.
      if (err instanceof ApiError && err.status === 409) await refresh();
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const transfer = () => {
    if (!draft) return;
    const ids = new Set(topic.blocks.map((block) => block.id));
    setError(null);
    setSince(null);
    commit({
      ...draft,
      base_revision: revision,
      // A block deleted in the newer revision comes back as a new block.
      blocks: draft.blocks.map((block) => (block.id && !ids.has(block.id) ? { ...block, id: "" } : block)),
      language: needsLanguage ? draft.language : null,
      updated_at: new Date().toISOString(),
    });
  };

  const discard = () => {
    discardDraft(course, run, topicId);
    setConfirmDiscard(false);
    setError(null);
    setSince(null);
    setPersisted(true);
  };

  const showSince = async () => {
    if (!draft) return;
    setLoadingSince(true);
    try {
      setSince(await getNotesRevision(course, run, draft.base_revision));
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setLoadingSince(false);
    }
  };

  const sinceTopic =
    since && since.info.revision === draft?.base_revision
      ? since.document.sections.flatMap((s) => s.topics).find((t) => t.topic_id === topicId)
      : undefined;
  const sinceChange = sinceTopic ? diffTopic(sinceTopic, topic) : null;

  const taken = new Set([
    ...document.sections.flatMap((s) => s.topics).flatMap((t) => t.blocks.flatMap((b) => figureLabels(b.content))),
    ...working.blocks.flatMap((block) => figureLabels(block.content)),
  ]);
  const figureBlock = working.blocks.findIndex((block) => block.key === figureFor);

  return (
    <section aria-label="Topic editor" className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {draft ? (
            <Badge className="bg-warning/15 text-warning">Unsaved draft</Badge>
          ) : (
            <Badge variant="outline">No unsaved changes</Badge>
          )}
          <span>Based on revision {working.base_revision}</span>
        </div>
        <p className="text-xs text-muted-foreground">
          {draft
            ? "The draft is kept in this browser tab only. The preview and downloads show saved, rendered revisions, so they don't include it."
            : `Text revision ${revision} is saved. Edits start a draft in this tab.`}
        </p>
        {!persisted && (
          <p className="text-xs text-warning">
            This browser didn&apos;t keep the draft in session storage, so a reload loses it.
          </p>
        )}
      </div>

      {topic.verification_stale ? (
        <Alert className="border-warning/40">
          <ShieldAlertIcon className="text-warning" />
          <AlertTitle>Verification outdated</AlertTitle>
          <AlertDescription>
            This topic changed after its last check, so it stays Unresolved until it is verified
            again.
          </AlertDescription>
        </Alert>
      ) : (
        topic.status === "verified" && (
          <p className="text-xs text-muted-foreground">
            Saving changes marks this topic Unresolved until it is verified again.
          </p>
        )
      )}

      {stale && draft && (
        <Alert className="border-warning/40">
          <TriangleAlertIcon className="text-warning" />
          <AlertTitle>
            Revision {revision} was saved after this draft started
          </AlertTitle>
          <AlertDescription className="flex flex-col items-start gap-3">
            <p>
              Your draft is based on revision {draft.base_revision} and is kept here unchanged.
              Review what changed, then transfer the draft to revision {revision} or discard it.
              After a transfer, saving makes your draft this topic&apos;s text, so changes from
              revision {revision} that your draft lacks are replaced. The history keeps every
              revision.
            </p>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" disabled={loadingSince} onClick={showSince}>
                {loadingSince ? <Spinner /> : <GitCompareIcon />}
                Show changes since revision {draft.base_revision}
              </Button>
              <Button size="sm" onClick={transfer}>
                Transfer draft to revision {revision}
              </Button>
              <Button variant="outline" size="sm" onClick={() => setConfirmDiscard(true)}>
                Discard draft
              </Button>
            </div>
            {sinceChange &&
              (hasChanges(sinceChange) ? (
                <div className="w-full">
                  <TopicDiff change={sinceChange} showTitle={false} />
                </div>
              ) : (
                <p>This topic&apos;s text is the same in revision {revision}.</p>
              ))}
          </AlertDescription>
        </Alert>
      )}

      {error && (
        <Alert variant="destructive">
          <CircleAlertIcon />
          <AlertTitle>Not saved</AlertTitle>
          <AlertDescription>
            {/[.!?]$/.test(error) ? error : `${error}.`} Your draft is kept in this tab.
          </AlertDescription>
        </Alert>
      )}

      {needsLanguage && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="notes-language">Notes language</Label>
          <Select
            value={working.language}
            onValueChange={(language) => language && update({ language: language as "uk" | "en" })}
            items={LANGUAGES}
          >
            <SelectTrigger id="notes-language" aria-label="Notes language" className="w-full sm:w-60">
              <SelectValue placeholder="Choose a language" />
            </SelectTrigger>
            <SelectContent>
              {LANGUAGES.map((language) => (
                <SelectItem key={language.value} value={language.value}>
                  {language.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            This run doesn&apos;t record the language of its notes. Choose it before saving; the
            notes are rendered with it.
          </p>
        </div>
      )}

      <AiAssist
        key={topicId}
        course={course}
        run={run}
        revision={revision}
        topic={topic}
        hasDraft={draft !== null}
        refresh={refresh}
      />

      {working.blocks.map((block, index) => (
        <BlockEditor
          key={block.key}
          index={index}
          count={working.blocks.length}
          block={block}
          evidence={topic.evidence}
          onChange={(patch) =>
            setBlocks((blocks) => blocks.map((b) => (b.key === block.key ? { ...b, ...patch } : b)))
          }
          onMove={(delta) => moveBlock(index, delta)}
          onRemove={() => setBlocks((blocks) => blocks.filter((b) => b.key !== block.key))}
          onAddBelow={() => addBlock(index + 1)}
          onInsertImage={() => setFigureFor(block.key)}
          onCaret={(position) => carets.current.set(block.key, position)}
        />
      ))}

      <Button variant="outline" className="self-start" onClick={() => addBlock(working.blocks.length)}>
        <PlusIcon />
        Add block
      </Button>

      <div className="sticky bottom-0 flex flex-wrap items-center gap-2 border-t bg-background py-3">
        <Button
          disabled={!draft || saving || (needsLanguage && !working.language)}
          onClick={save}
        >
          {saving ? <Spinner /> : <SaveIcon />}
          Save changes
        </Button>
        <Button variant="outline" disabled={!draft || saving} onClick={() => setConfirmDiscard(true)}>
          <Undo2Icon />
          Discard draft
        </Button>
        {needsLanguage && !working.language && (
          <span className="text-xs text-muted-foreground">Choose the notes language to save.</span>
        )}
      </div>

      {figureFor !== null && figureBlock >= 0 && (
        <FigureDialog
          course={course}
          run={run}
          open
          onOpenChange={(open) => !open && setFigureFor(null)}
          block={`block ${figureBlock + 1}`}
          defaultLabel={nextFigureLabel(topicId, taken)}
          taken={taken}
          onInsert={(markdown) => insertFigure(figureFor, markdown)}
        />
      )}

      <Dialog open={confirmDiscard} onOpenChange={setConfirmDiscard}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Discard your draft of {topicId}?</DialogTitle>
            <DialogDescription>
              Your unsaved changes are removed from this tab. Saved revisions stay as they are.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmDiscard(false)}>
              Keep draft
            </Button>
            <Button variant="destructive" onClick={discard}>
              Discard
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
