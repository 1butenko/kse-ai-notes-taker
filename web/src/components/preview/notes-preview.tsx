"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ExternalLinkIcon, FileTextIcon, LinkIcon, PencilLineIcon } from "lucide-react";
import { toast } from "sonner";

import { TOPIC_STATUS } from "@/components/dashboard/notes-stage";
import { artifactRevision, RevisionTag, revisionLine } from "@/components/notes/artifact-revision";
import { useDraftTopics, useTopicDraft } from "@/components/notes/draft";
import { TopicEditor } from "@/components/notes/editor";
import { LeaveDialog, useLeaveGuard } from "@/components/notes/leave-guard";
import { RevisionHistory } from "@/components/notes/revision-history";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Item, ItemActions, ItemContent, ItemGroup, ItemTitle } from "@/components/ui/item";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  getNotesRun,
  notesFileUrl,
  previewPath,
  topicNotesUrl,
  type NotesDocument,
  type NotesRunView,
} from "@/lib/api";

const FULL = "full";
// While editing, picks up revisions saved in other tabs. Refreshes never touch the draft.
const REFRESH_MS = 20_000;

type Mode = "preview" | "edit" | "history";

type NotesPreviewProps = {
  course: string;
  run: string;
  topicId: string | null;
  /**
   * The run as the server loaded it. Browser Back can replay an old copy, so the page
   * reloads it on mount, on focus, when Edit/History opens, and after saves and restores.
   */
  view: NotesRunView & { document: NotesDocument };
};

export function NotesPreview({ course, run, topicId, view: initial }: NotesPreviewProps) {
  const [view, setView] = useState(initial);
  const [chosenMode, setChosenMode] = useState<Mode | null>(null);
  const [preferredFormat, setPreferredFormat] = useState<"html" | "pdf">("html");
  const { document, current_revision: textRevision, artifacts } = view;
  const withPdf = new Set(view.topic_pdfs);
  const section = document.sections.find((s) => s.topics.some((t) => t.topic_id === topicId));
  const note = section?.topics.find((t) => t.topic_id === topicId);
  const available = artifacts.filter(
    (a) => (a.topic_id ?? null) === topicId && a.status === "ready",
  );
  const html = available.find((a) => a.format === "html");
  const hasPdf = note ? withPdf.has(note.topic_id) : view.pdf;
  const format = preferredFormat === "html" && html ? "html" : hasPdf ? "pdf" : "html";
  const url = (format === "html" ? html : hasPdf)
    ? note
      ? topicNotesUrl(course, run, note.topic_id, format)
      : notesFileUrl(course, run, format)
    : null;
  const shownRevision = artifactRevision(artifacts, format, topicId);

  const draft = useTopicDraft(course, run, note ? note.topic_id : null);
  const drafts = useDraftTopics(course, run);
  // A draft found after a reload (sessionStorage is read after hydration) opens the editor.
  if (chosenMode === null && note && draft) setChosenMode("edit");
  const mode: Mode = chosenMode ?? "preview";
  const guard = useLeaveGuard(draft !== null);

  const apply = useCallback((next: NotesRunView) => {
    const document = next.document;
    // HEAD never moves back, so a slower, older answer must not replace a newer one.
    if (document) {
      setView((prev) => (next.current_revision < prev.current_revision ? prev : { ...next, document }));
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const next = await getNotesRun(course, run);
      apply(next);
      return next;
    } catch {
      return null;
    }
  }, [course, run, apply]);

  useEffect(() => {
    let cancelled = false;
    getNotesRun(course, run).then(
      (next) => !cancelled && apply(next),
      () => {},
    );
    return () => {
      cancelled = true;
    };
  }, [course, run, apply]);

  useEffect(() => {
    const visible = () => {
      if (window.document.visibilityState === "visible") refresh();
    };
    window.addEventListener("focus", visible);
    window.document.addEventListener("visibilitychange", visible);
    const timer = mode === "preview" ? undefined : setInterval(visible, REFRESH_MS);
    return () => {
      clearInterval(timer);
      window.removeEventListener("focus", visible);
      window.document.removeEventListener("visibilitychange", visible);
    };
  }, [mode, refresh]);

  const choose = (next: Mode) => {
    setChosenMode(next);
    if (next !== "preview") refresh();
  };

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      toast.success("Link copied");
    } catch {
      toast.error("Couldn't copy the link");
    }
  };

  const items = [
    { value: FULL, label: "Full notes" },
    ...document.sections.flatMap((s) =>
      s.topics.map((t) => ({ value: t.topic_id, label: `${t.topic_id} ${t.title}` })),
    ),
  ];

  const frame = (title: string) =>
    url ? (
      <iframe
        key={url}
        src={url}
        title={title}
        sandbox={format === "html" ? "allow-scripts" : undefined}
        referrerPolicy="no-referrer"
        className="min-h-0 w-full flex-1 rounded-lg border"
      />
    ) : (
      <Empty className="flex-1 border border-dashed">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <FileTextIcon />
          </EmptyMedia>
          <EmptyTitle>No preview for this {note ? "topic" : "run"}</EmptyTitle>
          <EmptyDescription>
            {note?.status === "no_evidence"
              ? "None of the session materials covered this topic, so it has no notes."
              : note?.status === "failed"
                ? "Writing this topic failed. Generate a new run to retry it."
                : "The notes weren't rendered for this run."}
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );

  const artifactNote = url && (
    <span className="text-xs text-muted-foreground">
      {revisionLine(format.toUpperCase(), shownRevision, textRevision)}
    </span>
  );

  return (
    <div className="flex h-svh flex-col">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-3">
        <Link href="/" onNavigate={guard.onNavigate("/")} className="text-lg font-semibold tracking-tight">
          KSE Notes
        </Link>
        <Separator orientation="vertical" className="hidden h-6 sm:block" />
        <div className="order-3 min-w-0 basis-full sm:order-none sm:flex-1 sm:basis-auto">
          <h1 className="truncate font-medium">{note ? note.title : document.title}</h1>
          <p className="truncate text-sm text-muted-foreground">
            {note && section ? `${section.title} · ${document.title}` : "Full lecture notes"}
          </p>
        </div>
        <div className="ml-auto flex flex-wrap gap-2">
          <Button variant="outline" onClick={copyLink}>
            <LinkIcon />
            Copy link
          </Button>
          {url && (
            <a href={url} target="_blank" rel="noreferrer" className={buttonVariants()}>
              <ExternalLinkIcon />
              Open {format.toUpperCase()}
              <RevisionTag revision={shownRevision} text={textRevision} />
            </a>
          )}
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <nav
          aria-label="Topics"
          className="hidden w-80 shrink-0 flex-col gap-4 overflow-y-auto border-r p-3 md:flex"
        >
          <Item
            size="sm"
            variant={note ? "default" : "muted"}
            render={
              <Link
                href={previewPath(course, run)}
                onNavigate={guard.onNavigate(previewPath(course, run))}
              />
            }
          >
            <ItemContent>
              <ItemTitle>Full notes</ItemTitle>
            </ItemContent>
          </Item>
          {document.sections.map((s, i) => (
            <div key={i} className="flex flex-col gap-1">
              <p className="px-3 text-xs font-medium text-muted-foreground uppercase">{s.title}</p>
              <ItemGroup className="gap-1">
                {s.topics.map((t) => (
                  <Item
                    key={t.topic_id}
                    size="xs"
                    variant={t.topic_id === topicId ? "muted" : "default"}
                    aria-current={t.topic_id === topicId ? "page" : undefined}
                    render={
                      <Link
                        href={previewPath(course, run, t.topic_id)}
                        onNavigate={guard.onNavigate(previewPath(course, run, t.topic_id))}
                      />
                    }
                  >
                    <ItemContent className="min-w-0">
                      <ItemTitle className="line-clamp-2 block w-full">
                        <span className="text-muted-foreground">{t.topic_id}</span> {t.title}
                      </ItemTitle>
                    </ItemContent>
                    {(t.status !== "verified" || drafts.has(t.topic_id)) && (
                      <ItemActions>
                        {drafts.has(t.topic_id) && <Badge variant="outline">Draft</Badge>}
                        {t.status !== "verified" && (
                          <Badge className={TOPIC_STATUS[t.status].className}>
                            {TOPIC_STATUS[t.status].label}
                          </Badge>
                        )}
                      </ItemActions>
                    )}
                  </Item>
                ))}
              </ItemGroup>
            </div>
          ))}
        </nav>

        <main className="flex min-w-0 flex-1 flex-col gap-3 p-3">
          <Select
            value={topicId ?? FULL}
            onValueChange={(value) =>
              value && guard.push(previewPath(course, run, value === FULL ? undefined : value))
            }
            items={items}
          >
            <SelectTrigger className="w-full md:hidden" aria-label="Topic">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={FULL}>Full notes</SelectItem>
              {document.sections.map((s, i) => (
                <SelectGroup key={i}>
                  <SelectLabel>{s.title}</SelectLabel>
                  {s.topics.map((t) => (
                    <SelectItem key={t.topic_id} value={t.topic_id}>
                      {t.topic_id} {t.title}
                    </SelectItem>
                  ))}
                </SelectGroup>
              ))}
            </SelectContent>
          </Select>

          <Tabs
            value={mode}
            onValueChange={(value) => choose(value as Mode)}
            className="min-h-0 flex-1"
          >
            <div className="flex flex-wrap items-center gap-2">
              <TabsList>
                <TabsTrigger value="preview">Preview</TabsTrigger>
                {note && <TabsTrigger value="edit">Edit</TabsTrigger>}
                <TabsTrigger value="history">History</TabsTrigger>
              </TabsList>
              <span className="text-xs font-medium">Text revision {textRevision}</span>
              {note && note.status !== "verified" && (
                <Badge className={TOPIC_STATUS[note.status].className}>
                  {TOPIC_STATUS[note.status].label}
                </Badge>
              )}
              {note?.verification_stale && (
                <Badge variant="outline" title="Edited after its last check">
                  Verification outdated
                </Badge>
              )}
            </div>

            <TabsContent value="preview" className="flex min-h-0 flex-col gap-3">
              {note && draft && (
                <Alert className="border-warning/40">
                  <PencilLineIcon className="text-warning" />
                  <AlertTitle>Unsaved draft of this topic</AlertTitle>
                  <AlertDescription className="flex flex-col items-start gap-2">
                    It is based on revision {draft.base_revision} and isn&apos;t in this preview.
                    <Button size="sm" variant="outline" onClick={() => choose("edit")}>
                      Open the editor
                    </Button>
                  </AlertDescription>
                </Alert>
              )}
              <div className="flex flex-wrap items-center gap-2">
                <div role="group" aria-label="Preview format" className="flex gap-1">
                  <Button
                    size="sm"
                    variant={format === "html" ? "default" : "outline"}
                    disabled={!html}
                    aria-pressed={format === "html"}
                    onClick={() => setPreferredFormat("html")}
                  >
                    HTML
                  </Button>
                  <Button
                    size="sm"
                    variant={format === "pdf" ? "default" : "outline"}
                    disabled={!hasPdf}
                    aria-pressed={format === "pdf"}
                    onClick={() => setPreferredFormat("pdf")}
                  >
                    PDF · Print
                  </Button>
                </div>
                {artifactNote}
              </div>
              {frame(note ? note.title : document.title)}
            </TabsContent>

            {note && (
              <TabsContent value="edit" className="min-h-0 overflow-y-auto">
                <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                  <TopicEditor
                    course={course}
                    run={run}
                    revision={textRevision}
                    document={document}
                    topic={note}
                    draft={draft}
                    refresh={refresh}
                  />
                  <aside
                    aria-label="Saved preview"
                    className="sticky top-0 hidden h-[calc(100svh-10rem)] flex-col gap-2 xl:flex"
                  >
                    <p className="text-xs text-muted-foreground">
                      Saved preview. Unsaved edits don&apos;t appear here.{" "}
                      {url && revisionLine(format.toUpperCase(), shownRevision, textRevision)}
                    </p>
                    {frame(`Saved preview: ${note.title}`)}
                  </aside>
                </div>
              </TabsContent>
            )}

            <TabsContent value="history" className="min-h-0 overflow-y-auto">
              <RevisionHistory
                course={course}
                run={run}
                revision={textRevision}
                document={document}
                drafts={drafts}
                refresh={refresh}
              />
            </TabsContent>
          </Tabs>
        </main>
      </div>

      <LeaveDialog {...guard.dialog} what={note ? `${note.topic_id} ${note.title}` : "this topic"} />
    </div>
  );
}
