"use client";

import { useState } from "react";
import { CircleAlertIcon, InfoIcon, RefreshCwIcon, SparklesIcon } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  ApiError,
  transcribeSyllabus,
  type Reading,
  type SavedFile,
  type Session,
  type SessionReading,
  type Transcript,
} from "@/lib/api";

const TRANSCRIBABLE = /\.(pdf|docx)$/i;

type Status =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "done"; transcript: Transcript }
  | { kind: "error"; message: string };

function ReadingText({ reading }: { reading: Reading }) {
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

function ReadingList({ title, readings }: { title: string; readings: SessionReading[] }) {
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

function SessionRow({ session }: { session: Session }) {
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
      <ReadingList title="Required" readings={session.required_readings} />
      <ReadingList title="Optional" readings={session.optional_readings} />
    </li>
  );
}

function TranscriptView({ transcript }: { transcript: Transcript }) {
  const materials = transcript.learning_materials;
  return (
    <div className="flex flex-col gap-4">
      {transcript.notes && (
        <Alert>
          <InfoIcon />
          <AlertDescription>{transcript.notes}</AlertDescription>
        </Alert>
      )}

      {materials.length > 0 && (
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
      )}

      {transcript.sessions.length > 0 ? (
        <ol className="flex flex-col gap-2">
          {transcript.sessions.map((session, index) => (
            <SessionRow key={index} session={session} />
          ))}
        </ol>
      ) : (
        <p className="text-sm text-muted-foreground">No session plan found.</p>
      )}
    </div>
  );
}

function SyllabusFilePlan({ file }: { file: SavedFile }) {
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const name = file.path.split("/").pop() ?? file.path;
  const canTranscribe = TRANSCRIBABLE.test(name);

  const run = async (force: boolean) => {
    setStatus({ kind: "loading" });
    try {
      setStatus({ kind: "done", transcript: await transcribeSyllabus(file.path, force) });
    } catch (err) {
      setStatus({
        kind: "error",
        message:
          err instanceof ApiError ? err.message : "Couldn't reach the server. Please try again.",
      });
    }
  };

  const done = status.kind === "done";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="truncate" title={name}>
          {name}
        </CardTitle>
        <CardDescription>
          {canTranscribe
            ? "Extract the session plan and learning materials from this syllabus."
            : "Only PDF and DOCX syllabi can be transcribed."}
        </CardDescription>
        {canTranscribe && (
          <CardAction>
            <Button
              variant={done ? "outline" : "default"}
              size="sm"
              disabled={status.kind === "loading"}
              onClick={() => run(done)}
            >
              {done ? <RefreshCwIcon /> : <SparklesIcon />}
              {status.kind === "loading" ? "Transcribing…" : done ? "Re-run" : "Transcribe"}
            </Button>
          </CardAction>
        )}
      </CardHeader>

      {(status.kind === "done" || status.kind === "error") && (
        <CardContent>
          {status.kind === "error" ? (
            <Alert variant="destructive">
              <CircleAlertIcon />
              <AlertTitle>Couldn&apos;t transcribe the syllabus</AlertTitle>
              <AlertDescription>{status.message}</AlertDescription>
            </Alert>
          ) : (
            <TranscriptView transcript={status.transcript} />
          )}
        </CardContent>
      )}
    </Card>
  );
}

export function SyllabusPlan({ files }: { files: SavedFile[] }) {
  if (files.length === 0) return null;
  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-lg font-semibold tracking-tight">Syllabus plan</h2>
      {files.map((file) => (
        <SyllabusFilePlan key={file.path} file={file} />
      ))}
    </section>
  );
}
