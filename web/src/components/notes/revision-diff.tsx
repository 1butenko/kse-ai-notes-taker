import { Badge } from "@/components/ui/badge";
import type { EvidenceItem } from "@/lib/api";
import { cn } from "@/lib/utils";

import { diffLines, type BlockChange, type TopicChange } from "./diff";

const CHANGE_LABELS: Record<BlockChange["type"], { label: string; className: string }> = {
  added: { label: "Added", className: "bg-success/10 text-success" },
  removed: { label: "Removed", className: "bg-destructive/10 text-destructive" },
  changed: { label: "Changed", className: "bg-warning/15 text-warning" },
  moved: { label: "Moved", className: "bg-secondary text-secondary-foreground" },
};

export function evidenceLabel(item: EvidenceItem | undefined, chunk: string): string {
  if (!item) return chunk;
  return item.page ? `${item.title}, p. ${item.page}` : item.title;
}

function TextDiff({ before, after }: { before: string; after: string }) {
  return (
    <div
      aria-label="Old and new text"
      className="overflow-x-auto rounded-md border bg-muted/30 font-mono text-xs leading-relaxed"
    >
      {diffLines(before, after).map((line, i) => {
        const text = line.text || " ";
        if (line.type === "removed") {
          return (
            <del key={i} className="block bg-destructive/10 px-2 whitespace-pre-wrap no-underline">
              <span aria-hidden className="select-none text-destructive">− </span>
              {text}
            </del>
          );
        }
        if (line.type === "added") {
          return (
            <ins key={i} className="block bg-success/10 px-2 whitespace-pre-wrap no-underline">
              <span aria-hidden className="select-none text-success">+ </span>
              {text}
            </ins>
          );
        }
        return (
          <div key={i} className="px-2 whitespace-pre-wrap text-muted-foreground">
            <span aria-hidden className="select-none">{"  "}</span>
            {text}
          </div>
        );
      })}
    </div>
  );
}

function BlockText({ text, tone }: { text: string; tone: "added" | "removed" }) {
  const Tag = tone === "added" ? "ins" : "del";
  return (
    <Tag
      className={cn(
        "block overflow-x-auto rounded-md border px-2 py-1 font-mono text-xs leading-relaxed whitespace-pre-wrap no-underline",
        tone === "added" ? "bg-success/10" : "bg-destructive/10",
      )}
    >
      {text || " "}
    </Tag>
  );
}

function Citations({
  before,
  after,
  evidence,
}: {
  before: string[];
  after: string[];
  evidence: Map<string, EvidenceItem>;
}) {
  const all = [...new Set([...before, ...after])];
  if (all.length === 0) return <p className="text-xs text-muted-foreground">No citations.</p>;
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <span className="text-muted-foreground">Citations:</span>
      {all.map((chunk) => {
        const label = evidenceLabel(evidence.get(chunk), chunk);
        const added = !before.includes(chunk);
        const removed = !after.includes(chunk);
        if (added) {
          return (
            <ins key={chunk} className="rounded-full bg-success/10 px-2 py-0.5 text-success no-underline">
              + {label}
            </ins>
          );
        }
        if (removed) {
          return (
            <del key={chunk} className="rounded-full bg-destructive/10 px-2 py-0.5 text-destructive">
              − {label}
            </del>
          );
        }
        return (
          <Badge key={chunk} variant="outline">
            {label}
          </Badge>
        );
      })}
    </div>
  );
}

function BlockChangeView({
  change,
  evidence,
}: {
  change: BlockChange;
  evidence: Map<string, EvidenceItem>;
}) {
  const block = change.type === "removed" ? change.before : change.after;
  const heading = `Block ${change.position} · ${block.kind}${block.title ? ` · ${block.title}` : ""}`;
  const status = CHANGE_LABELS[change.type];
  return (
    <article
      aria-label={`${status.label}: ${heading}`}
      className="flex min-w-0 flex-col gap-2 rounded-lg border p-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge className={status.className}>{status.label}</Badge>
        {change.type === "changed" && change.moved && <Badge variant="outline">Moved</Badge>}
        <span className="min-w-0 text-sm font-medium break-words">{heading}</span>
        <code className="text-xs text-muted-foreground">{block.id}</code>
      </div>
      {change.type === "changed" && (
        <>
          {change.fields.includes("kind") && (
            <p className="text-xs">
              Kind: <del>{change.before.kind}</del> → <ins className="no-underline">{change.after.kind}</ins>
            </p>
          )}
          {change.fields.includes("title") && (
            <p className="text-xs break-words">
              Title: <del>{change.before.title ?? "none"}</del> →{" "}
              <ins className="no-underline">{change.after.title ?? "none"}</ins>
            </p>
          )}
          {change.fields.includes("content") && (
            <TextDiff before={change.before.content} after={change.after.content} />
          )}
          <Citations
            before={change.before.citations}
            after={change.after.citations}
            evidence={evidence}
          />
        </>
      )}
      {change.type === "added" && (
        <>
          <BlockText text={change.after.content} tone="added" />
          <Citations before={change.after.citations} after={change.after.citations} evidence={evidence} />
        </>
      )}
      {change.type === "removed" && (
        <>
          <BlockText text={change.before.content} tone="removed" />
          <Citations before={change.before.citations} after={change.before.citations} evidence={evidence} />
        </>
      )}
      {change.type === "moved" && (
        <p className="text-xs text-muted-foreground">Same text, now at block {change.position}.</p>
      )}
    </article>
  );
}

/** What changed in one topic between two revisions, block by block. */
export function TopicDiff({ change, showTitle = true }: { change: TopicChange; showTitle?: boolean }) {
  const evidence = new Map(
    [...change.before.evidence, ...change.after.evidence].map((item) => [item.chunk_id, item]),
  );
  return (
    <section aria-label={`Changes to ${change.topic_id}`} className="flex min-w-0 flex-col gap-3">
      {showTitle && (
        <h3 className="font-medium">
          <span className="text-muted-foreground">{change.topic_id}</span> {change.after.title}
        </h3>
      )}
      {change.title && (
        <p className="text-sm break-words">
          Topic title: <del>{change.before.title}</del> →{" "}
          <ins className="no-underline">{change.after.title}</ins>
        </p>
      )}
      {change.objectives && (
        <p className="text-sm text-muted-foreground">The learning objectives changed.</p>
      )}
      {change.blocks.map((block) => (
        <BlockChangeView
          key={`${block.type}:${block.type === "removed" ? block.before.id : block.after.id}`}
          change={block}
          evidence={evidence}
        />
      ))}
      {change.blocks.length === 0 && !change.title && !change.objectives && (
        <p className="text-sm text-muted-foreground">No block changed.</p>
      )}
      {change.unchanged > 0 && (
        <p className="text-xs text-muted-foreground">
          {change.unchanged === 1 ? "1 other block is" : `${change.unchanged} other blocks are`}{" "}
          unchanged.
        </p>
      )}
    </section>
  );
}
