import type { ReactNode } from "react";
import { InfoIcon } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
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

export function ReadingList({ title, readings }: { title: string; readings: SessionReading[] }) {
  if (readings.length === 0) return null;
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-medium text-muted-foreground">{title}</span>
      <ul className="flex flex-col gap-1 text-sm">
        {readings.map((reading, index) => (
          <li key={index} className="flex gap-2">
            <ReadingText reading={reading} />
            {reading.material_ref !== null && (
              <Badge variant="outline">→ #{reading.material_ref + 1}</Badge>
            )}
          </li>
        ))}
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

export function CourseMaterialsList({ transcript }: { transcript: Transcript }) {
  const materials = transcript.learning_materials;
  if (materials.length === 0) return null;
  return (
    <details className="rounded-lg border p-3">
      <summary className="cursor-pointer font-medium">
        All course materials ({materials.length})
      </summary>
      <ol className="mt-2 flex list-decimal flex-col gap-1 pl-5 text-sm">
        {materials.map((reading, index) => (
          <li key={index}>
            <ReadingText reading={reading} />
          </li>
        ))}
      </ol>
    </details>
  );
}

/** One session: heading, subtopics and the readings the syllabus lists, plus optional extras. */
export function SessionBlock({ session, children }: { session: Session; children?: ReactNode }) {
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
      <ReadingList title="Required" readings={session.required_readings} />
      <ReadingList title="Optional" readings={session.optional_readings} />
      {children}
    </li>
  );
}
