import type { NoteBlock, NotesDocument, TopicNote } from "@/lib/api";

export type BlockField = "kind" | "title" | "content" | "citations";

/** One block's change between two versions of a topic, matched by block ID. */
export type BlockChange =
  | { type: "added"; after: NoteBlock; position: number }
  | { type: "removed"; before: NoteBlock; position: number }
  | {
      type: "changed";
      before: NoteBlock;
      after: NoteBlock;
      fields: BlockField[];
      moved: boolean;
      position: number;
    }
  | { type: "moved"; before: NoteBlock; after: NoteBlock; position: number };

export type TopicChange = {
  topic_id: string;
  before: TopicNote;
  after: TopicNote;
  title: boolean;
  objectives: boolean;
  blocks: BlockChange[];
  unchanged: number;
};

export type DiffLine = { type: "same" | "removed" | "added"; text: string };

const sameSet = (a: string[], b: string[]) =>
  a.length === b.length && [...a].sort().join("\n") === [...b].sort().join("\n");

function changedFields(before: NoteBlock, after: NoteBlock): BlockField[] {
  const fields: BlockField[] = [];
  if (before.kind !== after.kind) fields.push("kind");
  if ((before.title ?? "") !== (after.title ?? "")) fields.push("title");
  if (before.content !== after.content) fields.push("content");
  if (!sameSet(before.citations, after.citations)) fields.push("citations");
  return fields;
}

/** Longest common subsequence of two lists, as index pairs. */
function lcs<T>(a: T[], b: T[], equal: (x: T, y: T) => boolean): [number, number][] {
  const table = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      table[i][j] = equal(a[i], b[j])
        ? table[i + 1][j + 1] + 1
        : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }
  const pairs: [number, number][] = [];
  for (let i = 0, j = 0; i < a.length && j < b.length; ) {
    if (equal(a[i], b[j])) {
      pairs.push([i, j]);
      i++;
      j++;
    } else if (table[i + 1][j] >= table[i][j + 1]) i++;
    else j++;
  }
  return pairs;
}

/**
 * Compares two versions of a topic block by block ID: added, removed, changed and moved
 * blocks, listed in the new order with each removed block after its old predecessor.
 */
export function diffTopic(before: TopicNote, after: TopicNote): TopicChange {
  const old = new Map(before.blocks.map((block, index) => [block.id, { block, index }]));
  const kept = new Set(after.blocks.filter((block) => old.has(block.id)).map((block) => block.id));
  // Blocks outside the longest common order are the ones that moved.
  const oldOrder = before.blocks.filter((block) => kept.has(block.id)).map((block) => block.id);
  const newOrder = after.blocks.filter((block) => kept.has(block.id)).map((block) => block.id);
  const stayed = new Set(lcs(oldOrder, newOrder, (x, y) => x === y).map(([i]) => oldOrder[i]));

  // Removed blocks follow the nearest earlier block that still exists, or lead the list.
  const removedAfter = new Map<string | null, BlockChange[]>();
  let anchor: string | null = null;
  before.blocks.forEach((block, index) => {
    if (kept.has(block.id)) {
      anchor = block.id;
      return;
    }
    const list = removedAfter.get(anchor) ?? [];
    list.push({ type: "removed", before: block, position: index + 1 });
    removedAfter.set(anchor, list);
  });

  const blocks: BlockChange[] = [...(removedAfter.get(null) ?? [])];
  let unchanged = 0;
  after.blocks.forEach((block, index) => {
    const previous = old.get(block.id);
    if (!previous || !block.id) {
      blocks.push({ type: "added", after: block, position: index + 1 });
    } else {
      const fields = changedFields(previous.block, block);
      const moved = !stayed.has(block.id);
      const position = index + 1;
      if (fields.length > 0) {
        blocks.push({ type: "changed", before: previous.block, after: block, fields, moved, position });
      } else if (moved) {
        blocks.push({ type: "moved", before: previous.block, after: block, position });
      } else {
        unchanged++;
      }
      blocks.push(...(removedAfter.get(block.id) ?? []));
    }
  });

  return {
    topic_id: after.topic_id,
    before,
    after,
    title: before.title !== after.title,
    objectives: before.objectives.join("\n") !== after.objectives.join("\n"),
    blocks,
    unchanged,
  };
}

export function hasChanges(change: TopicChange): boolean {
  return change.title || change.objectives || change.blocks.length > 0;
}

/** Topics whose authored content differs between two revisions, in document order. */
export function diffDocuments(before: NotesDocument, after: NotesDocument): TopicChange[] {
  const old = new Map(before.sections.flatMap((s) => s.topics).map((t) => [t.topic_id, t]));
  return after.sections
    .flatMap((s) => s.topics)
    .flatMap((topic) => {
      const previous = old.get(topic.topic_id);
      const change = previous && diffTopic(previous, topic);
      return change && hasChanges(change) ? [change] : [];
    });
}

/** A line-level diff of a block's Markdown, for showing old and new text together. */
export function diffLines(before: string, after: string): DiffLine[] {
  const a = before.split("\n");
  const b = after.split("\n");
  if (a.length * b.length > 250_000) {
    return [
      ...a.map((text) => ({ type: "removed" as const, text })),
      ...b.map((text) => ({ type: "added" as const, text })),
    ];
  }
  const lines: DiffLine[] = [];
  let i = 0;
  let j = 0;
  for (const [x, y] of [...lcs(a, b, (p, q) => p === q), [a.length, b.length]]) {
    while (i < x) lines.push({ type: "removed", text: a[i++] });
    while (j < y) lines.push({ type: "added", text: b[j++] });
    if (x < a.length) lines.push({ type: "same", text: a[x] });
    i = x + 1;
    j = y + 1;
  }
  return lines;
}
