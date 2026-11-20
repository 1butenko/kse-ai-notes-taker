"use client";

/** Edit a lecture's notes (the newest published ones) like a Notion page. Saving turns the
 * blocks back into the Quarto body and has the server render it; the rendered page replaces the
 * notes. Until it is published, the edit is kept as a draft in this browser. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CircleAlertIcon, HistoryIcon, SaveIcon } from "lucide-react";
import { Plate, PlateContent, usePlateEditor } from "platejs/react";
import { toast } from "sonner";

import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import {
  ApiError,
  getLectureNotesSource,
  lectureNotesSiteUrl,
  listLectureNotes,
  saveLectureNotesEdit,
  visualNotesPath,
  type LectureNotesSource,
  type NoteIssue,
} from "@/lib/api";
import { parseQmd, serializeQmd } from "@/lib/qmd/convert";
import { createMarkdownEditor } from "@/lib/qmd/markdown-editor";

import { NotesEditorContext } from "./context";
import { clearDraft, readDraft, writeDraft } from "./draft";
import { InsertMenu, MentionMenu, type MenuTarget, triggerAt } from "./insert-menu";
import { editorPlugins } from "./plugins";
import { SelectionToolbar } from "./selection-toolbar";
import "./notes-editor.css";

type NotesEditorProps = { course: string; sessionId: string };

export function NotesEditor({ course, sessionId }: NotesEditorProps) {
  const [source, setSource] = useState<LectureNotesSource | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listLectureNotes(course, sessionId)
      .then((runs) => {
        const newest = runs.find((r) => r.status === "succeeded");
        if (!newest) throw new ApiError("These notes aren't published yet.", 404);
        return getLectureNotesSource(newest.id);
      })
      .then(setSource, (err) =>
        setError(err instanceof ApiError ? err.message : "Couldn't reach the server."),
      );
  }, [course, sessionId]);

  const back = visualNotesPath(course, sessionId);
  if (error) {
    return (
      <div className="mx-auto w-full max-w-3xl p-6">
        <Alert variant="destructive">
          <CircleAlertIcon />
          <AlertTitle>Couldn&apos;t open the notes for editing</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
          <AlertAction>
            <Link href={back} className={buttonVariants({ variant: "outline", size: "sm" })}>
              Back to the notes
            </Link>
          </AlertAction>
        </Alert>
      </div>
    );
  }
  if (!source) {
    return (
      <div className="flex flex-1 items-center justify-center p-12">
        <Spinner className="size-6 text-muted-foreground" />
      </div>
    );
  }
  return <Editor course={course} sessionId={sessionId} source={source} back={back} />;
}

// One headless editor converts for every editor on the page; it holds no document.
const converter = createMarkdownEditor();

function Editor({
  course,
  sessionId,
  source,
  back,
}: {
  course: string;
  sessionId: string;
  source: LectureNotesSource;
  back: string;
}) {
  const router = useRouter();
  const runId = source.run_id;
  const [draft] = useState(() => {
    const saved = readDraft(runId);
    return saved && saved.body !== source.body ? saved : null;
  });
  const [restored, setRestored] = useState(!!draft);
  const initial = useMemo(
    () => parseQmd(converter, draft?.body ?? source.body),
    [draft, source.body],
  );
  const editor = usePlateEditor({ plugins: editorPlugins, value: initial as never });
  const [dirty, setDirty] = useState(!!draft);
  const [saving, setSaving] = useState(false);
  const [issues, setIssues] = useState<{ issues: NoteIssue[]; body: string } | null>(null);
  const [menu, setMenu] = useState<MenuTarget | null>(null);
  const [linking, setLinking] = useState(false);
  // SVG figures added here, by name; sent with the save.
  const [newAssets, setNewAssets] = useState<Record<string, string>>(() => draft?.assets ?? {});
  const assetsRef = useRef(newAssets);
  useEffect(() => {
    assetsRef.current = newAssets;
  }, [newAssets]);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const body = useCallback(() => serializeQmd(converter, editor.children as never), [editor]);

  // Keep a draft while editing; warn before leaving with unsaved changes.
  const onChange = () => {
    setDirty(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => writeDraft(runId, body(), assetsRef.current), 800);
  };
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  useEffect(() => () => clearTimeout(timer.current), []);

  const discardDraft = () => {
    clearTimeout(timer.current);
    clearDraft(runId);
    editor.tf.setValue(parseQmd(converter, source.body) as never);
    setNewAssets({});
    setRestored(false);
    setDirty(false);
  };

  const save = async () => {
    const text = body();
    if (text.trim() === source.body.trim()) {
      toast.info("Nothing changed.");
      return;
    }
    clearTimeout(timer.current);
    writeDraft(runId, text, newAssets);
    setSaving(true);
    setIssues(null);
    try {
      // Only the figures the note still shows.
      const assets = Object.fromEntries(
        Object.entries(newAssets).filter(([name]) => text.includes(name)),
      );
      const run = await saveLectureNotesEdit(runId, text, assets);
      setDirty(false);
      router.push(visualNotesPath(course, sessionId, run.id));
    } catch (err) {
      if (err instanceof ApiError && err.status === 422 && Array.isArray(err.detail)) {
        setIssues({ issues: err.detail as NoteIssue[], body: text });
      } else {
        toast.error(err instanceof ApiError ? err.message : "Couldn't reach the server.");
      }
    } finally {
      setSaving(false);
    }
  };

  const context = useMemo(() => {
    const assetNames = [...new Set([...source.assets, ...Object.keys(newAssets)])];
    return {
      source,
      assetNames,
      assetUrl: (name: string) =>
        name in newAssets
          ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(newAssets[name])}`
          : lectureNotesSiteUrl(runId, name),
      addAsset: (fileName: string, svg: string) => {
        const base =
          fileName
            .toLowerCase()
            .replace(/\.svg$/, "")
            .replace(/[^a-z0-9-]+/g, "-")
            .replace(/^-+|-+$/g, "")
            .slice(0, 50) || "figure";
        let name = `assets/${base}.svg`;
        for (let n = 2; assetNames.includes(name) && newAssets[name] !== svg; n++) {
          name = `assets/${base}-${n}.svg`;
        }
        setNewAssets((current) => ({ ...current, [name]: svg }));
        setDirty(true);
        return name;
      },
      openInsertMenu: (path: number[]) => setMenu({ menu: "insert", path }),
    };
  }, [source, runId, newAssets]);

  return (
    <NotesEditorContext.Provider value={context}>
      <Plate editor={editor} onValueChange={onChange}>
        <main className="-mt-px flex h-[calc(100svh-4rem)] min-h-96 flex-col">
          <div className="relative bg-background">
            <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center gap-3 px-4 py-2 sm:px-6">
              <div className="min-w-0 flex-1 truncate text-sm text-muted-foreground">
                {saving ? "Saving…" : dirty ? "Unsaved changes, kept in this browser" : "Editing the notes"}
              </div>
              <Link href={back} className={buttonVariants({ variant: "ghost" })}>
                Cancel
              </Link>
              <Button onClick={save} disabled={saving}>
                {saving ? <Spinner data-icon="inline-start" /> : <SaveIcon data-icon="inline-start" />}
                Save
              </Button>
            </div>
          </div>

          <div className="flex min-h-0 flex-1 flex-col bg-primary p-1.5 sm:p-2">
            <div className="min-h-0 flex-1 overflow-y-auto rounded-xl bg-background">
              <div className="mx-auto flex max-w-[46rem] flex-col gap-3 py-10 pr-4 pl-16 sm:pr-8">
                {restored && (
                  <Alert>
                    <HistoryIcon />
                    <AlertTitle>Your unsaved changes are back</AlertTitle>
                    <AlertDescription>
                      This browser kept them from your last edit of these notes.
                    </AlertDescription>
                    <AlertAction>
                      <Button variant="outline" size="sm" onClick={discardDraft}>
                        Discard them
                      </Button>
                    </AlertAction>
                  </Alert>
                )}
                {issues && <IssuesAlert {...issues} />}
                <PlateContent
                  className="kse-notes min-h-[60vh] pb-32 outline-none"
                  placeholder="Type / for blocks, @ to cite"
                  onKeyDown={(e) => {
                    if (e.ctrlKey || e.metaKey || e.altKey) return;
                    const target = triggerAt(editor, e.key);
                    // Let the character be typed, then open its menu.
                    if (target) requestAnimationFrame(() => setMenu(target));
                  }}
                  onKeyDownCapture={(e) => {
                    if (!(e.ctrlKey || e.metaKey)) return;
                    if (e.key === "s") {
                      e.preventDefault();
                      void save();
                    } else if (e.key === "k" && editor.api.isExpanded()) {
                      e.preventDefault();
                      setLinking(true);
                    }
                  }}
                />
              </div>
            </div>
          </div>
        </main>
        <InsertMenu target={menu} onClose={() => setMenu(null)} />
        <MentionMenu target={menu} onClose={() => setMenu(null)} />
        <SelectionToolbar linking={linking} onLinkingChange={setLinking} />
      </Plate>
    </NotesEditorContext.Provider>
  );
}

function IssuesAlert({ issues, body }: { issues: NoteIssue[]; body: string }) {
  const lines = body.split("\n");
  return (
    <Alert variant="destructive">
      <CircleAlertIcon />
      <AlertTitle>The notes weren&apos;t saved</AlertTitle>
      <AlertDescription>
        <p>Fix these and save again:</p>
        <ul className="flex list-disc flex-col gap-1 pl-5">
          {issues.map((issue, i) => (
            <li key={i}>
              {issue.message}
              {issue.line > 0 && lines[issue.line - 1]?.trim() && (
                <code className="mt-0.5 block truncate rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-foreground">
                  {lines[issue.line - 1].trim()}
                </code>
              )}
            </li>
          ))}
        </ul>
      </AlertDescription>
    </Alert>
  );
}
