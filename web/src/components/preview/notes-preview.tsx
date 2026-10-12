"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ExternalLinkIcon, FileTextIcon, LinkIcon } from "lucide-react";
import { toast } from "sonner";

import { TOPIC_STATUS } from "@/components/dashboard/notes-stage";
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
import {
  notesFileUrl,
  previewPath,
  topicPdfUrl,
  type NotesDocument,
} from "@/lib/api";

const FULL = "full";

type NotesPreviewProps = {
  course: string;
  run: string;
  session: string;
  topicId: string | null;
  document: NotesDocument;
  pdf: boolean;
  topicPdfs: string[];
};

export function NotesPreview({
  course,
  run,
  session,
  topicId,
  document,
  pdf,
  topicPdfs,
}: NotesPreviewProps) {
  const router = useRouter();
  const withPdf = new Set(topicPdfs);
  const section = document.sections.find((s) => s.topics.some((t) => t.topic_id === topicId));
  const note = section?.topics.find((t) => t.topic_id === topicId);
  const url = note
    ? withPdf.has(note.topic_id)
      ? topicPdfUrl(course, run, note.topic_id, session)
      : null
    : pdf
      ? notesFileUrl(course, run, "pdf", session)
      : null;

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

  return (
    <div className="flex h-svh flex-col">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-3">
        <Link href="/" className="text-lg font-semibold tracking-tight">
          KSE Notes
        </Link>
        <Separator orientation="vertical" className="hidden h-6 sm:block" />
        <div className="min-w-0 flex-1">
          <h1 className="truncate font-medium">{note ? note.title : document.title}</h1>
          <p className="truncate text-sm text-muted-foreground">
            {note && section ? `${section.title} · ${document.title}` : "Full lecture notes"}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={copyLink}>
            <LinkIcon />
            Copy link
          </Button>
          {url && (
            <a href={url} target="_blank" rel="noreferrer" className={buttonVariants()}>
              <ExternalLinkIcon />
              Open PDF
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
            render={<Link href={previewPath(course, run, undefined, session)} />}
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
                    render={<Link href={previewPath(course, run, t.topic_id, session)} />}
                  >
                    <ItemContent className="min-w-0">
                      <ItemTitle className="line-clamp-2 block w-full">
                        <span className="text-muted-foreground">{t.topic_id}</span> {t.title}
                      </ItemTitle>
                    </ItemContent>
                    {t.status !== "verified" && (
                      <ItemActions>
                        <Badge className={TOPIC_STATUS[t.status].className}>
                          {TOPIC_STATUS[t.status].label}
                        </Badge>
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
              value && router.push(previewPath(course, run, value === FULL ? undefined : value, session))
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

          {url ? (
            <iframe
              key={url}
              src={url}
              title={note ? note.title : document.title}
              className="min-h-0 w-full flex-1 rounded-lg border"
            />
          ) : (
            <Empty className="flex-1 border border-dashed">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <FileTextIcon />
                </EmptyMedia>
                <EmptyTitle>No PDF for this {note ? "topic" : "run"}</EmptyTitle>
                <EmptyDescription>
                  {note?.status === "no_evidence"
                    ? "None of the session materials covered this topic, so it has no notes."
                    : note?.status === "failed"
                      ? "Writing this topic failed. Resume the run to retry it."
                      : "The PDF wasn't typeset for this run."}
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}
        </main>
      </div>
    </div>
  );
}
