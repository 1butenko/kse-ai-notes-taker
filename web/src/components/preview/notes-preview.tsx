"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { DownloadIcon, ExternalLinkIcon, FileTextIcon, LinkIcon, PencilLineIcon } from "lucide-react";
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
  getRenderJob,
  renderNotesRevision,
  revisionArtifactUrl,
  revisionBookUrl,
  previewPath,
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
  const requested = useRef(0);
  const accepted = useRef(0);
  const [retrying, setRetrying] = useState(false);
  const [chosenMode, setChosenMode] = useState<Mode | null>(null);
  const [preferredFormat, setPreferredFormat] = useState<"html" | "pdf">("html");
  const [showBook, setShowBook] = useState(false);
  const [bookStarting, setBookStarting] = useState(false);
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
  const shownRevision = artifactRevision(artifacts, format, topicId);
  const shownArtifact = available.find((a) => a.format === format);
  const url = (format === "html" ? html : hasPdf)
    ? revisionArtifactUrl(course, run, shownRevision, format, topicId)
    : null;

  // Word is prepared on demand for one revision. A file from an older revision is labelled
  // as such and is never offered as the current download.
  const wordFile = available.find((a) => a.format === "docx");
  const wordCurrent = wordFile?.revision === textRevision;
  const job = view.render;
  const wordJob = job?.formats.includes("docx") ? job : null;
  const documentJob = job?.formats.some((f) => f === "html" || f === "pdf") ? job : null;
  const wordPending = wordJob !== null && ["queued", "running"].includes(wordJob.status);
  const wordFailed = wordJob?.status === "failed" && !wordCurrent;
  const bookFile = artifacts.find((a) => a.topic_id === null && a.format === "book" && a.status === "ready");
  const bookCurrent = bookFile?.revision === textRevision;
  const bookJob = job?.formats.includes("book") ? job : null;
  const bookPending = bookJob !== null && ["queued", "running"].includes(bookJob.status);
  const bookFailed = bookJob?.status === "failed" && !bookCurrent;
  const openUrl = showBook && !note && bookFile
    ? revisionBookUrl(course, run, bookFile.revision)
    : url;
  const openLabel = showBook && !note && bookFile ? "Course book" : format.toUpperCase();
  const openRevision = showBook && !note && bookFile ? bookFile.revision : shownRevision;
  const [wordStarting, setWordStarting] = useState(false);

  const draft = useTopicDraft(course, run, note ? note.topic_id : null);
  const drafts = useDraftTopics(course, run);
  // A draft found after a reload (sessionStorage is read after hydration) opens the editor.
  if (chosenMode === null && note && draft) setChosenMode("edit");
  const mode: Mode = chosenMode ?? "preview";
  const guard = useLeaveGuard(draft !== null);

  const apply = useCallback((next: NotesRunView, sequence: number) => {
    const document = next.document;
    // Render completion changes artifacts without advancing HEAD. Order every
    // refresh, including the mount request, so a delayed equal-revision answer
    // cannot replace a newer manifest or return a completed job to pending.
    if (document && sequence >= accepted.current) {
      accepted.current = sequence;
      setView((prev) => (next.current_revision < prev.current_revision ? prev : { ...next, document }));
    }
  }, []);

  const refresh = useCallback(async () => {
    const sequence = ++requested.current;
    try {
      const next = await getNotesRun(course, run);
      apply(next, sequence);
      return next;
    } catch {
      return null;
    }
  }, [course, run, apply]);

  useEffect(() => {
    let cancelled = false;
    const sequence = ++requested.current;
    getNotesRun(course, run).then(
      (next) => !cancelled && apply(next, sequence),
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

  const pendingJob = job && (job.status === "queued" || job.status === "running") ? job.id : null;
  useEffect(() => {
    if (!pendingJob) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    // Poll this job; once it has finished, reload the run for its artifacts and labels.
    const poll = async () => {
      try {
        const polled = await getRenderJob(course, run, pendingJob);
        if (cancelled) return;
        if (polled.status === "done" || polled.status === "failed") {
          // The reloaded view's latest job decides whether polling continues.
          if (await refresh()) return;
        }
      } catch {
        // A temporary connection failure keeps the saved preview; keep polling.
      }
      if (!cancelled) timer = setTimeout(poll, 1_000);
    };
    timer = setTimeout(poll, 500);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [course, run, pendingJob, refresh]);

  // Rendering never calls a model: it rebuilds files for a saved revision.
  const retry = async () => {
    setRetrying(true);
    try {
      await renderNotesRevision(course, run, documentJob?.revision ?? textRevision,
        documentJob?.formats.filter((f) => f === "html" || f === "pdf") ?? ["html", "pdf"]);
      await refresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not start rendering");
    } finally {
      setRetrying(false);
    }
  };

  // Prepares only Word, for the revision on screen; HTML and PDF are left as they are.
  const prepareWord = async () => {
    setWordStarting(true);
    try {
      await renderNotesRevision(course, run, textRevision, ["docx"]);
      await refresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not start preparing Word");
    } finally {
      setWordStarting(false);
    }
  };

  const prepareBook = async () => {
    setBookStarting(true);
    try {
      await renderNotesRevision(course, run, textRevision, ["book"]);
      await refresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not start the course book");
    } finally {
      setBookStarting(false);
    }
  };

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
        key={`${url}:${shownArtifact?.path ?? "legacy"}`}
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

  const artifactNote = openUrl && (
    <span className="text-xs text-muted-foreground">
      {revisionLine(openLabel, openRevision, textRevision)}
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
          {openUrl && (
            <a href={openUrl} target="_blank" rel="noreferrer" className={buttonVariants()}>
              <ExternalLinkIcon />
              Open {openLabel}
              <RevisionTag revision={openRevision} text={textRevision} />
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

          {documentJob && ["queued", "running"].includes(documentJob.status) && (
            <p role="status" className="text-sm text-muted-foreground">
              Rendering revision {documentJob.revision}. Saved text is safe; the preview keeps its labelled version.
            </p>
          )}
          {documentJob?.status === "failed" && (
            <Alert variant="destructive">
              <AlertTitle>Could not render revision {documentJob.revision}</AlertTitle>
              <AlertDescription>
                <p>Your saved text and previous files are kept.</p>
                {documentJob.errors.map((error, index) => <p key={index}>{error}</p>)}
                <Button size="sm" variant="outline" onClick={retry} disabled={retrying}>
                  {retrying ? "Starting…" : "Retry render"}
                </Button>
              </AlertDescription>
            </Alert>
          )}
          {!documentJob && (!url || shownRevision < textRevision) && (
            <Button size="sm" variant="outline" onClick={retry} disabled={retrying} className="self-start">
              Render revision {textRevision}
            </Button>
          )}

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
                    variant={format === "html" && !showBook ? "default" : "outline"}
                    disabled={!html}
                    aria-pressed={format === "html" && !showBook}
                    onClick={() => { setPreferredFormat("html"); setShowBook(false); }}
                  >
                    HTML
                  </Button>
                  <Button
                    size="sm"
                    variant={format === "pdf" && !showBook ? "default" : "outline"}
                    disabled={!hasPdf}
                    aria-pressed={format === "pdf" && !showBook}
                    onClick={() => { setPreferredFormat("pdf"); setShowBook(false); }}
                  >
                    PDF · Print
                  </Button>
                  {!note && bookFile && (
                    <Button size="sm" variant={showBook ? "default" : "outline"}
                      aria-pressed={showBook} onClick={() => setShowBook(true)}>
                      Course book
                    </Button>
                  )}
                </div>
                {artifactNote}
                <Separator orientation="vertical" className="hidden h-6 sm:block" />
                <div role="group" aria-label="Word" className="flex flex-wrap items-center gap-2">
                  {wordCurrent ? (
                    <a
                      href={revisionArtifactUrl(course, run, textRevision, "docx", topicId)}
                      download
                      className={buttonVariants({ variant: "outline", size: "sm" })}
                    >
                      <DownloadIcon />
                      Download Word
                      <RevisionTag revision={textRevision} text={textRevision} />
                    </a>
                  ) : (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={prepareWord}
                      disabled={wordPending || wordStarting}
                    >
                      <DownloadIcon />
                      {wordPending || wordStarting
                        ? "Preparing Word…"
                        : wordFailed
                          ? "Retry Word"
                          : "Prepare Word"}
                    </Button>
                  )}
                  {wordFile && !wordCurrent && (
                    <a
                      href={revisionArtifactUrl(course, run, wordFile.revision, "docx", topicId)}
                      download
                      className="text-xs text-muted-foreground underline"
                    >
                      Older Word file · revision {wordFile.revision}
                    </a>
                  )}
                  {wordPending && wordJob && (
                    <span role="status" className="text-xs text-muted-foreground">
                      Preparing Word for revision {wordJob.revision}. Your text is safe.
                    </span>
                  )}
                </div>
              </div>
              {!note && (
                <div role="group" aria-label="Course book" className="flex flex-wrap items-center gap-2">
                  {bookFile && (
                    <a href={revisionBookUrl(course, run, bookFile.revision)} target="_blank" rel="noreferrer"
                      className={buttonVariants({ variant: "outline", size: "sm" })}>
                      Open course book <RevisionTag revision={bookFile.revision} text={textRevision} />
                    </a>
                  )}
                  {!bookCurrent && (
                    <Button size="sm" variant="outline" onClick={prepareBook}
                      disabled={bookPending || bookStarting}>
                      {bookPending || bookStarting ? "Preparing course book…" : bookFailed ? "Retry course book" : "Prepare course book"}
                    </Button>
                  )}
                  {bookFile && !bookCurrent && <span className="text-xs text-muted-foreground">Older course book · revision {bookFile.revision}</span>}
                  {bookPending && <span role="status" className="text-xs text-muted-foreground">Preparing course book for revision {bookJob.revision}.</span>}
                  {bookFailed && <span role="alert" className="text-xs text-destructive">Could not prepare course book for revision {bookJob.revision}. Your saved text and previous files are kept.</span>}
                </div>
              )}
              {wordFailed && wordJob && (
                <Alert variant="destructive">
                  <AlertTitle>Could not prepare Word for revision {wordJob.revision}</AlertTitle>
                  <AlertDescription>
                    <p>Your saved text, HTML and PDF are kept.</p>
                    {wordJob.errors.map((error, index) => (
                      <p key={index}>{error}</p>
                    ))}
                  </AlertDescription>
                </Alert>
              )}
              {!note && showBook && bookFile ? (
                <iframe src={revisionBookUrl(course, run, bookFile.revision)} title="Course book"
                  sandbox="allow-scripts" referrerPolicy="no-referrer"
                  className="min-h-0 w-full flex-1 rounded-lg border" />
              ) : frame(note ? note.title : document.title)}
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
