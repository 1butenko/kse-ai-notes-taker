import { useMemo, useSyncExternalStore } from "react";

import type { NoteBlock, TopicNote } from "@/lib/api";

/** A block being edited; `key` keeps React identity for new blocks, whose id is empty. */
export type DraftBlock = NoteBlock & { key: string };

/** An unsaved topic edit, kept per browser tab in sessionStorage. */
export type TopicDraft = {
  /** The revision the draft started from. It changes only by an explicit transfer. */
  base_revision: number;
  blocks: DraftBlock[];
  /** Chosen for a document whose language is unknown; otherwise null. */
  language: "uk" | "en" | null;
  updated_at: string;
};

// Keys hold course/run/topic/base_revision, so a draft never moves to another base by itself.
const PREFIX = "kse-notes:draft:";

function topicPrefix(course: string, run: string, topic: string): string {
  return `${PREFIX}${[course, run, topic].map(encodeURIComponent).join("/")}@`;
}

function runPrefix(course: string, run: string): string {
  return `${PREFIX}${[course, run].map(encodeURIComponent).join("/")}/`;
}

// When sessionStorage is unavailable or full, drafts live in memory until the page unloads.
const memory = new Map<string, string>();
const listeners = new Set<() => void>();

function storage(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function storedKeys(): string[] {
  const keys = new Set(memory.keys());
  try {
    const store = storage();
    for (let i = 0; store && i < store.length; i++) {
      const key = store.key(i);
      if (key?.startsWith(PREFIX)) keys.add(key);
    }
  } catch {
    // Unreadable storage: only the in-memory drafts remain.
  }
  return [...keys];
}

function read(key: string): string | null {
  if (memory.has(key)) return memory.get(key) ?? null;
  try {
    return storage()?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function remove(key: string): void {
  memory.delete(key);
  try {
    storage()?.removeItem(key);
  } catch {
    // Nothing else to clean up.
  }
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function emit(): void {
  for (const listener of listeners) listener();
}

function parse(value: string | null): TopicDraft | null {
  if (!value) return null;
  try {
    const draft = JSON.parse(value);
    if (!Number.isInteger(draft?.base_revision) || !Array.isArray(draft?.blocks)) return null;
    return draft as TopicDraft;
  } catch {
    return null;
  }
}

/** The newest draft of a topic, whatever its base revision. */
function topicSnapshot(course: string, run: string, topic: string): string {
  const prefix = topicPrefix(course, run, topic);
  let newest = "";
  let newestAt = "";
  for (const key of storedKeys()) {
    if (!key.startsWith(prefix)) continue;
    const value = read(key);
    const draft = parse(value);
    if (draft && (!newest || draft.updated_at > newestAt)) {
      newest = value ?? "";
      newestAt = draft.updated_at;
    }
  }
  return newest;
}

function draftTopics(course: string, run: string): string {
  const prefix = runPrefix(course, run);
  const topics = new Set<string>();
  for (const key of storedKeys()) {
    if (!key.startsWith(prefix)) continue;
    try {
      topics.add(decodeURIComponent(key.slice(prefix.length, key.lastIndexOf("@"))));
    } catch {
      // Not a key this module wrote.
    }
  }
  return [...topics].sort().join("\n");
}

/** The tab's saved draft for a topic, found even when HEAD moved past its base revision. */
export function useTopicDraft(course: string, run: string, topic: string | null): TopicDraft | null {
  const value = useSyncExternalStore(
    subscribe,
    () => (topic ? topicSnapshot(course, run, topic) : ""),
    () => "",
  );
  return useMemo(() => parse(value), [value]);
}

/** The tab's draft for a topic right now, outside React (e.g. after an await). */
export function currentDraft(course: string, run: string, topic: string): TopicDraft | null {
  return parse(topicSnapshot(course, run, topic));
}

/** Topics of this run that have a draft in this tab. */
export function useDraftTopics(course: string, run: string): Set<string> {
  const value = useSyncExternalStore(subscribe, () => draftTopics(course, run), () => "");
  return useMemo(() => new Set(value ? value.split("\n") : []), [value]);
}

/** Keeps one draft per topic. Returns false when only memory holds it (lost on reload). */
export function writeDraft(course: string, run: string, topic: string, draft: TopicDraft): boolean {
  const key = `${topicPrefix(course, run, topic)}${draft.base_revision}`;
  for (const other of storedKeys()) {
    if (other !== key && other.startsWith(topicPrefix(course, run, topic))) remove(other);
  }
  const value = JSON.stringify(draft);
  let persisted = false;
  try {
    const store = storage();
    if (store) {
      store.setItem(key, value);
      persisted = true;
    }
  } catch {
    persisted = false;
  }
  if (persisted) memory.delete(key);
  else memory.set(key, value);
  emit();
  return persisted;
}

export function discardDraft(course: string, run: string, topic: string): void {
  const prefix = topicPrefix(course, run, topic);
  for (const key of storedKeys()) if (key.startsWith(prefix)) remove(key);
  emit();
}

export function draftBlocks(topic: TopicNote): DraftBlock[] {
  return topic.blocks.map((block) => ({ ...block, key: block.id }));
}

/** The saved form of draft blocks: the API needs no React keys, and an empty title is none. */
export function patchBlocks(blocks: DraftBlock[]): NoteBlock[] {
  return blocks.map(({ id, kind, title, content, citations }) => ({
    id,
    kind,
    title: title?.trim() ? title : null,
    content,
    citations,
  }));
}

/** Whether saving `a` over `b` changes nothing; citation order carries no meaning. */
export function sameBlocks(a: DraftBlock[], b: DraftBlock[]): boolean {
  const canonical = (blocks: DraftBlock[]) =>
    JSON.stringify(
      patchBlocks(blocks).map((block) => ({ ...block, citations: [...block.citations].sort() })),
    );
  return canonical(a) === canonical(b);
}
