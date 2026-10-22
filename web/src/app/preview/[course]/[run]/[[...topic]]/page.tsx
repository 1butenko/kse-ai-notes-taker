import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cache } from "react";
import { CircleAlertIcon, LoaderIcon } from "lucide-react";

import { NotesPreview } from "@/components/preview/notes-preview";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { fetchNotesRun } from "@/lib/api";

type Props = PageProps<"/preview/[course]/[run]/[[...topic]]">;

const load = cache(async (course: string, run: string) =>
  fetchNotesRun(course, run).catch(() => undefined),
);

export async function generateMetadata(props: Props): Promise<Metadata> {
  const { course, run, topic } = await props.params;
  const view = await load(course, run);
  const document = view?.document;
  if (!document) return { title: "Lecture notes · KSE Notes" };
  const note = document.sections.flatMap((s) => s.topics).find((t) => t.topic_id === topic?.[0]);
  return {
    title: note ? `${note.title} · ${document.title}` : document.title,
    description: note
      ? `A topic of the ${document.title} lecture notes, generated with KSE Notes.`
      : `Lecture notes for ${document.title}, generated with KSE Notes.`,
  };
}

function Message({ title, description, busy }: { title: string; description: string; busy?: boolean }) {
  return (
    <div className="flex flex-1 items-center justify-center p-4">
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">{busy ? <LoaderIcon /> : <CircleAlertIcon />}</EmptyMedia>
          <EmptyTitle>{title}</EmptyTitle>
          <EmptyDescription>{description}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    </div>
  );
}

export default async function PreviewPage(props: Props) {
  const { course, run, topic } = await props.params;
  if (topic && topic.length > 1) notFound();
  const view = await load(course, run);

  if (view === undefined) {
    return (
      <Message
        title="Notes are unavailable"
        description="The notes server didn't answer. It may be waking up, so try again in a minute."
      />
    );
  }
  if (view === null) notFound();
  if (!view.document) {
    return (
      <Message
        busy={view.run.status !== "failed"}
        title={view.run.status === "failed" ? "Generation failed" : "Notes are being generated"}
        description={
          view.run.status === "failed"
            ? "This run didn't finish, so there is nothing to preview."
            : "Come back in a few minutes; this link will show the notes once they are ready."
        }
      />
    );
  }

  const topicId = topic?.[0] ?? null;
  if (topicId && !view.document.sections.some((s) => s.topics.some((t) => t.topic_id === topicId))) {
    notFound();
  }

  return (
    <NotesPreview
      course={course}
      run={run}
      topicId={topicId}
      document={view.document}
      textRevision={view.current_revision}
      pdf={view.pdf}
      topicPdfs={view.topic_pdfs}
      artifacts={view.artifacts ?? []}
    />
  );
}
