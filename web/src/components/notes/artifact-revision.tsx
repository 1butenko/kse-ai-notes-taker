import { Badge } from "@/components/ui/badge";
import type { RenderedArtifact, RenderFormat } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The text revision a shown file was rendered from. Files without a manifest entry are the
 * original generation's outputs, so revision 0.
 */
export function artifactRevision(
  artifacts: RenderedArtifact[],
  format: RenderFormat,
  topic: string | null,
): number {
  const entry = artifacts.find(
    (a) => a.format === format && (a.topic_id ?? null) === topic && a.status === "ready",
  );
  return entry?.revision ?? 0;
}

/** "rev. N", marked older when the saved text has moved past the file. */
export function RevisionTag({ revision, text }: { revision: number; text: number }) {
  const older = revision < text;
  return (
    <Badge
      variant="outline"
      title={older ? `Rendered from revision ${revision}; the text is at revision ${text}` : undefined}
      className={cn(older && "border-warning/40 text-warning")}
    >
      rev. {revision}
      {older && " · older"}
    </Badge>
  );
}

/** One line naming the text revision and the revision of the file that is shown. */
export function revisionLine(format: string, revision: number, text: number): string {
  return revision < text
    ? `${format} revision ${revision} · Older artifact: it doesn't include edits saved after revision ${revision}`
    : `${format} revision ${revision}`;
}
