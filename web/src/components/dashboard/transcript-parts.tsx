import type { ReactNode } from "react";
import { InfoIcon } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import type { Reading, Session, SessionReading, Transcript } from "@/lib/api";

export function ReadingText({ reading }: { reading: Reading }) {
  const link = reading.url && (
    <a href={reading.url} target="_blank" rel="noreferrer" className="underline">
      {reading.title ?? reading.url}
    </a>
  );
  return (
    <span>
      {reading.raw}
      {link && <> · {link}</>}
    </span>
  );
}

function bookName(book: Reading) {
  if (!book.title) return book.raw.replace(/^\[\d+\]\s*/, "");
  const byline = [book.authors.join(", "), book.year].filter(Boolean).join(", ");
  return byline ? `${book.title} (${byline})` : book.title;
}

export function ReadingList({
  title,
  readings,
  materials,
}: {
  title: string;
  readings: SessionReading[];
  materials: Reading[];
}) {
  if (readings.length === 0) return null;
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-medium text-muted-foreground">{title}</span>
      <ul className="flex flex-col gap-2 text-sm">
        {readings.map((reading, index) => {
          const book = reading.material_ref !== null ? materials[reading.material_ref] : undefined;
          if (!book) {
            return (
              <li key={index}>
                <ReadingText reading={reading} />
              </li>
            );
          }
          return (
            <li key={index} className="flex flex-col">
              <span className="font-medium">{bookName(book)}</span>
              <span className="text-muted-foreground">
                {reading.raw.replace(/^\[\d+\]\s*/, "")}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function TranscriptNotes({ transcript }: { transcript: Transcript }) {
  if (!transcript.notes) return null;
  return (
    <Alert>
      <InfoIcon />
      <AlertDescription>{transcript.notes}</AlertDescription>
    </Alert>
  );
}

/** One session: heading, subtopics and the readings the syllabus lists, plus optional extras. */
export function SessionBlock({
  session,
  materials,
  children,
}: {
  session: Session;
  materials: Reading[];
  children?: ReactNode;
}) {
  const hasReadings =
    session.required_readings.length > 0 || session.optional_readings.length > 0;
  return (
    <li className="flex flex-col gap-2 rounded-lg border p-3">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="font-medium">{session.label}</span>
        {session.date && <span className="text-sm text-muted-foreground">{session.date}</span>}
        <span className="text-sm">· {session.topic}</span>
      </div>
      {session.subtopics.length > 0 && (
        <ul className="list-disc pl-5 text-sm text-muted-foreground">
          {session.subtopics.map((subtopic, index) => (
            <li key={index}>{subtopic}</li>
          ))}
        </ul>
      )}
      {children && hasReadings && (
        <span className="text-xs font-semibold uppercase text-muted-foreground">
          From syllabus
        </span>
      )}
      <ReadingList title="Required" readings={session.required_readings} materials={materials} />
      <ReadingList title="Optional" readings={session.optional_readings} materials={materials} />
      {children}
    </li>
  );
}
