/** An unsaved edit of the notes (by the run it started from), kept in this browser until it is
 * published. Storage may be unavailable (private windows, blocked site data): then there is
 * simply no draft. */

const key = (runId: string) => `kse-notes:draft:${runId}`;

export type Draft = {
  body: string;
  /** SVG figures added in the editor, by name (`assets/x.svg`). */
  assets?: Record<string, string>;
  at: string;
};

export function readDraft(runId: string): Draft | null {
  try {
    const raw = localStorage.getItem(key(runId));
    return raw ? (JSON.parse(raw) as Draft) : null;
  } catch {
    return null;
  }
}

export function writeDraft(runId: string, body: string, assets: Record<string, string> = {}): void {
  try {
    const draft: Draft = { body, assets, at: new Date().toISOString() };
    localStorage.setItem(key(runId), JSON.stringify(draft));
  } catch {
    // No storage: nothing to keep.
  }
}

export function clearDraft(runId: string): void {
  try {
    localStorage.removeItem(key(runId));
  } catch {
    // No storage: nothing to clear.
  }
}
