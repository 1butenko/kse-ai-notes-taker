export const API_URL = process.env.API_URL ?? "http://localhost:8000";

export const PUBLIC_API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? `http://localhost:${process.env.API_PORT}`;

export type Course = {
  id: number;
  shortname: string;
  fullname: string;
  categoryid: number;
  summary: string;
  visible: number;
  startdate: number;
  enddate: number;
};

export type ModuleContent = {
  type: string;
  filename: string;
  fileurl: string;
  filesize: number;
  mimetype: string;
  timemodified: number;
};

export type Module = {
  id: number;
  name: string;
  modname: string;
  url: string;
  visible: number;
  contents: ModuleContent[];
};

export type Section = {
  id: number;
  section: number;
  name: string;
  summary: string;
  visible: number;
  modules: Module[];
};

export class ApiError extends Error {
  /** The HTTP status, or 0 when the server sent none. */
  readonly status: number;

  constructor(message: string, status = 0) {
    super(message);
    this.status = status;
  }
}

export type UploadCategory = "syllabus" | "reading";

export type SavedFile = {
  path: string;
  size: number;
};

export type MoodleFileRef = {
  fileurl: string;
  filename: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${PUBLIC_API_URL}${path}`, init);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : `Request failed (${res.status})`;
    throw new ApiError(detail, res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export function getCourse(courseId: number): Promise<Course> {
  return request(`/courses/${courseId}`);
}

export function getCourseContents(courseId: number): Promise<Section[]> {
  return request(`/courses/${courseId}/contents`);
}

export function uploadFiles(
  category: UploadCategory,
  files: File[],
  courseId?: number,
): Promise<SavedFile[]> {
  const form = new FormData();
  form.append("category", category);
  if (courseId) form.append("course_id", String(courseId));
  for (const file of files) form.append("files", file);
  return request("/uploads", { method: "POST", body: form });
}

export function uploadMoodleFiles(
  category: UploadCategory,
  files: MoodleFileRef[],
  courseId?: number,
): Promise<SavedFile[]> {
  return request("/uploads/moodle", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ category, course_id: courseId, files }),
  });
}

export type Reading = {
  raw: string;
  title: string | null;
  authors: string[];
  year: string | null;
  url: string | null;
  pages: string | null;
};

export type SessionReading = Reading & {
  material_ref: number | null;
};

export type Session = {
  label: string;
  number: number | null;
  date: string | null;
  topic: string;
  subtopics: string[];
  required_readings: SessionReading[];
  optional_readings: SessionReading[];
};

export type Transcript = {
  language: string | null;
  learning_materials: Reading[];
  sessions: Session[];
  notes: string | null;
  source_path: string;
  source_sha256: string;
  model: string;
  created_at: string;
};

export function transcribeSyllabus(path: string, force = false): Promise<Transcript> {
  return request(`/syllabus/transcribe${force ? "?force=true" : ""}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
}

export function deleteSyllabus(path: string): Promise<void> {
  return request(`/syllabus?path=${encodeURIComponent(path)}`, { method: "DELETE" });
}

export function getTranscript(path: string): Promise<Transcript> {
  return request(`/syllabus/transcript?path=${encodeURIComponent(path)}`);
}

export type CourseFiles = {
  syllabus: SavedFile[];
  reading: SavedFile[];
};

export type Excerpt = {
  book: string;
  label: string;
  pdf_start: number;
  pdf_end: number;
  printed: string | null;
};

export type FileView = SavedFile & {
  excerpt: Excerpt | null;
};

export type ProposalMethod = "pages" | "bookmarks" | "toc" | "manual";

export type Proposal = {
  id: string;
  session_id: string;
  reading: string;
  book: string;
  label: string;
  pdf_start: number | null;
  pdf_end: number | null;
  printed: string | null;
  method: ProposalMethod;
  note: string | null;
  status: "proposed" | "approved" | "rejected";
  excerpt: string | null;
};

export type SessionView = {
  id: string;
  session: Session;
  files: FileView[];
  proposals: Proposal[];
};

export type BookView = {
  material: number;
  raw: string;
  file: string | null;
  confirmed: boolean;
};

export type PlanView = {
  course: string;
  primary: string | null;
  transcript: Transcript | null;
  sessions: SessionView[];
  unassigned: FileView[];
  books: BookView[];
  mapped: boolean;
};

export function courseKey(courseId?: number): string {
  return courseId ? String(courseId) : "local";
}

export function listCourseFiles(course: string): Promise<CourseFiles> {
  return request(`/uploads/${course}`);
}

export function getPlan(course: string): Promise<PlanView> {
  return request(`/plans/${course}`);
}

function sendPath(method: string, url: string, path: string): Promise<PlanView> {
  return request(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
}

export function setPrimarySyllabus(course: string, path: string): Promise<PlanView> {
  return sendPath("PUT", `/plans/${course}/primary`, path);
}

export function attachFile(course: string, sessionId: string, path: string): Promise<PlanView> {
  return sendPath("POST", `/plans/${course}/sessions/${sessionId}/files`, path);
}

export function detachFile(course: string, sessionId: string, path: string): Promise<PlanView> {
  return request(
    `/plans/${course}/sessions/${sessionId}/files?path=${encodeURIComponent(path)}`,
    { method: "DELETE" },
  );
}

export function dismissUnassigned(course: string, path: string): Promise<PlanView> {
  return request(`/plans/${course}/unassigned?path=${encodeURIComponent(path)}`, {
    method: "DELETE",
  });
}

export function fileName(path: string): string {
  return path.split("/").pop() ?? path;
}

export function fileUrl(path: string, page?: number): string {
  const url = `${PUBLIC_API_URL}/files?path=${encodeURIComponent(path)}`;
  return page ? `${url}#page=${page}` : url;
}

export function mapMaterials(course: string): Promise<PlanView> {
  return request(`/plans/${course}/map`, { method: "POST" });
}

export function setBook(course: string, material: number, file: string | null): Promise<PlanView> {
  return request(`/plans/${course}/books/${material}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ file }),
  });
}

export function approveProposal(
  course: string,
  id: string,
  pages?: { pdf_start: number; pdf_end: number },
): Promise<PlanView> {
  return request(`/plans/${course}/proposals/${id}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(pages ?? {}),
  });
}

export function rejectProposal(course: string, id: string): Promise<PlanView> {
  return request(`/plans/${course}/proposals/${id}/reject`, { method: "POST" });
}

export function reopenProposal(course: string, id: string): Promise<PlanView> {
  return request(`/plans/${course}/proposals/${id}/reopen`, { method: "POST" });
}

export function approveAllProposals(course: string): Promise<PlanView> {
  return request(`/plans/${course}/proposals/approve-all`, { method: "POST" });
}

export function addExcerpt(
  course: string,
  sessionId: string,
  path: string,
  pages: { pdf_start: number; pdf_end: number },
): Promise<PlanView> {
  return request(`/plans/${course}/sessions/${sessionId}/excerpts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, ...pages }),
  });
}

export type NotesRunState = "queued" | "running" | "done" | "failed";

export type NotesRunEvent = {
  at: string;
  stage: string;
  message: string;
};

export type NotesRun = {
  id: string;
  course: string;
  status: NotesRunState;
  stage: string;
  created_at: string;
  updated_at: string;
  models: Record<string, string>;
  topics_total: number;
  topics_done: number;
  warnings: string[];
  error: string | null;
  events: NotesRunEvent[];
};

export type VerificationIssue = {
  block: number | null;
  kind: string;
  severity: "major" | "minor";
  detail: string;
  fix: string;
};

export type EvidenceItem = {
  chunk_id: string;
  source: number;
  title: string;
  page: string | null;
  role: string;
  relevance: number;
  reason: string;
  text: string;
};

export type NoteBlock = {
  id: string;
  kind: string;
  title: string | null;
  content: string;
  citations: string[];
};

export type TopicStatus = "verified" | "unresolved" | "no_evidence" | "failed";

export type TopicNote = {
  objectives: string[];
  topic_id: string;
  title: string;
  status: TopicStatus;
  blocks: NoteBlock[];
  evidence: EvidenceItem[];
  rounds: number;
  verifier: string | null;
  open_issues: VerificationIssue[];
  error: string | null;
  verification_stale: boolean;
};

export type NotesSource = {
  id: number;
  file: string;
  title: string;
  label: string | null;
  pdf_start: number | null;
  pdf_end: number | null;
  sessions: number[];
};

export type NoteAsset = {
  id: string;
  name: string;
  path: string;
  media_type: "image/png" | "image/jpeg";
  sha256: string;
  width: number;
  height: number;
};

export type NotesDocument = {
  /** Images that saved revisions reference; uploads alone are not listed. */
  assets: NoteAsset[];
  schema_version: number;
  language: "uk" | "en" | null;
  course: string;
  run: string;
  title: string;
  created_at: string;
  sections: { title: string; topics: TopicNote[] }[];
  sources: NotesSource[];
  models: Record<string, string>;
};

export type RenderFormat = "html" | "pdf" | "docx" | "book";

export type RenderedArtifact = {
  format: RenderFormat;
  path: string;
  revision: number;
  status: "ready" | "failed";
  error: string | null;
  topic_id: string | null;
};

export type NotesRunView = {
  run: NotesRun;
  /** The current revision's document; each artifact names the revision it shows. */
  document: NotesDocument | null;
  current_revision: number;
  display_revision: number | null;
  render: RenderJob | null;
  pdf: boolean;
  topic_pdfs: string[];
  artifacts: RenderedArtifact[];
};

export type RevisionInfo = {
  revision: number;
  parent: number | null;
  created_at: string;
  origin: "generation" | "manual" | "restore" | "ai" | "verification";
  changed_topics: string[];
  restored_from: number | null;
  /** Older stored revisions have neither field. */
  suggestion?: string | null;
  verification_job?: string | null;
};

export type RevisionView = {
  info: RevisionInfo;
  document: NotesDocument;
};

/** A topic's complete new block order; a block with an empty id is new. */
export type TopicPatch = {
  base_revision: number;
  blocks: NoteBlock[];
  language?: "uk" | "en" | null;
};

export type RenderJob = {
  id: string;
  revision: number;
  status: "queued" | "running" | "done" | "failed";
  formats: RenderFormat[];
  errors: string[];
};

export type EditResult = {
  revision: RevisionInfo;
  render: RenderJob | null;
};

export type Verification = {
  round: number;
  model: string;
  passed: boolean;
  issues: VerificationIssue[];
  escalate: boolean;
  escalation_reason: string | null;
};

export type SuggestionRequest = {
  base_revision: number;
  topic_id: string;
  /** Empty means the whole topic. */
  block_ids: string[];
  instruction: string;
};

export type NoteSuggestion = {
  id: string;
  base_revision: number;
  topic_id: string;
  status: "queued" | "running" | "ready" | "failed" | "applied" | "rejected";
  /** The complete proposed topic: every block, in its final order. */
  proposed_blocks: NoteBlock[];
  /** The fresh check of exactly `proposed_blocks`. */
  verification: Verification | null;
  error: string | null;
  block_ids: string[];
  instruction: string;
  /** True only for a clean check: no major issue and no escalation. */
  verified: boolean;
  /** Standing evidence gaps that keep the topic from being verified by any check. */
  blocking: VerificationIssue[];
  unsafe_citations: VerificationIssue[];
  applied_revision: number | null;
  /** Read-time compatibility hint for the reported current revision; Apply rechecks under lock. */
  current_revision: number | null;
  compatible: boolean;
};

export type VerificationJob = {
  id: string;
  topic_id: string;
  base_revision: number;
  status: "queued" | "running" | "done" | "failed";
  verification: Verification | null;
  verified: boolean;
  blocking: VerificationIssue[];
  /** The metadata revision that recorded the result. */
  revision: number | null;
  /** The notes changed while the check ran, so the result was not recorded. */
  conflict: boolean;
  error: string | null;
  refresh_note: string | null;
};

function notesPath(course: string, run: string): string {
  return `/plans/${encodeURIComponent(course)}/notes/${encodeURIComponent(run)}`;
}

function sendJson(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

/** The committed history, oldest first; uncommitted snapshots never appear. */
export function listNotesRevisions(course: string, run: string): Promise<RevisionInfo[]> {
  return request(`${notesPath(course, run)}/revisions`);
}

export function getNotesRevision(
  course: string,
  run: string,
  revision: number,
): Promise<RevisionView> {
  return request(`${notesPath(course, run)}/revisions/${revision}`);
}

/** Saves one topic as a new revision; HTTP 409 means `base_revision` is no longer current. */
export function saveNotesTopic(
  course: string,
  run: string,
  topic: string,
  patch: TopicPatch,
): Promise<EditResult> {
  return request(`${notesPath(course, run)}/topics/${encodeURIComponent(topic)}`, sendJson("PATCH", patch));
}

/** Copies an earlier revision's text into a new revision on top of `baseRevision`. */
export function restoreNotesRevision(
  course: string,
  run: string,
  revision: number,
  baseRevision: number,
): Promise<EditResult> {
  return request(
    `${notesPath(course, run)}/revisions/${revision}/restore`,
    sendJson("POST", { base_revision: baseRevision }),
  );
}

/** Asks the model to propose changes; nothing in the notes changes until it is applied. */
export function createNotesSuggestion(
  course: string,
  run: string,
  body: SuggestionRequest,
): Promise<NoteSuggestion> {
  return request(`${notesPath(course, run)}/suggestions`, sendJson("POST", body));
}

export function getNotesSuggestion(
  course: string,
  run: string,
  suggestion: string,
): Promise<NoteSuggestion> {
  return request(`${notesPath(course, run)}/suggestions/${encodeURIComponent(suggestion)}`);
}

/** Commits a reviewed suggestion; HTTP 409 means the candidate is no longer compatible. */
export function applyNotesSuggestion(
  course: string,
  run: string,
  suggestion: string,
  baseRevision: number,
): Promise<EditResult> {
  return request(
    `${notesPath(course, run)}/suggestions/${encodeURIComponent(suggestion)}/apply`,
    sendJson("POST", { base_revision: baseRevision }),
  );
}

export function rejectNotesSuggestion(
  course: string,
  run: string,
  suggestion: string,
): Promise<NoteSuggestion> {
  return request(
    `${notesPath(course, run)}/suggestions/${encodeURIComponent(suggestion)}/reject`,
    { method: "POST" },
  );
}

/** Rechecks a topic's saved text against its evidence, without rewriting it. */
export function verifyNotesTopic(
  course: string,
  run: string,
  topic: string,
  baseRevision: number,
): Promise<VerificationJob> {
  return request(
    `${notesPath(course, run)}/topics/${encodeURIComponent(topic)}/verify`,
    sendJson("POST", { base_revision: baseRevision }),
  );
}

export function getVerificationJob(
  course: string,
  run: string,
  job: string,
): Promise<VerificationJob> {
  return request(`${notesPath(course, run)}/verification-jobs/${encodeURIComponent(job)}`);
}

export type NoteAssetUpload = {
  asset: NoteAsset;
  /** The relative path a figure's Markdown uses, e.g. `assets/<sha256>.png`. */
  markdown_path: string;
};

/** Imports a PNG/JPEG into the run's catalog; no revision changes until one references it. */
export function uploadNoteAsset(course: string, run: string, file: File): Promise<NoteAssetUpload> {
  const form = new FormData();
  form.append("file", file);
  return request(`${notesPath(course, run)}/assets`, { method: "POST", body: form });
}

export function listNotesRuns(course: string): Promise<NotesRun[]> {
  return request(`/plans/${course}/notes`);
}

export function getNotesRun(course: string, run: string): Promise<NotesRunView> {
  return request(`/plans/${course}/notes/${run}`);
}

export function generateNotes(course: string, resume?: string): Promise<NotesRunView> {
  return request(`/plans/${course}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(resume ? { resume } : {}),
  });
}

/** Rebuild a saved revision's files; no model is called. */
export function renderNotesRevision(
  course: string,
  run: string,
  revision: number,
  formats: RenderFormat[] = ["html", "pdf"],
): Promise<RenderJob> {
  return request(
    `${notesPath(course, run)}/revisions/${revision}/render`,
    sendJson("POST", { formats }),
  );
}

export function getRenderJob(course: string, run: string, job: string): Promise<RenderJob> {
  return request(`${notesPath(course, run)}/render-jobs/${encodeURIComponent(job)}`);
}

/** The canonical URL of one revision's file; it never falls back to another revision. */
export function revisionArtifactUrl(
  course: string,
  run: string,
  revision: number,
  kind: RenderFormat,
  topic?: string | null,
): string {
  const scope = topic ? `/topics/${encodeURIComponent(topic)}` : "";
  return `${PUBLIC_API_URL}${notesPath(course, run)}/revisions/${revision}${scope}/artifacts/${kind}`;
}

export function revisionBookUrl(course: string, run: string, revision: number): string {
  return `${PUBLIC_API_URL}${notesPath(course, run)}/revisions/${revision}/book/`;
}

export function notesFileUrl(course: string, run: string, kind: RenderFormat | "qmd"): string {
  return `${PUBLIC_API_URL}/plans/${course}/notes/${run}/${kind}`;
}

export function topicPdfUrl(course: string, run: string, topic: string): string {
  return topicNotesUrl(course, run, topic, "pdf");
}

export function topicNotesUrl(course: string, run: string, topic: string, kind: "html" | "pdf"): string {
  return `${PUBLIC_API_URL}/plans/${course}/notes/${run}/topics/${encodeURIComponent(topic)}/${kind}`;
}

export function previewPath(course: string, run: string, topic?: string): string {
  const path = `/preview/${encodeURIComponent(course)}/${encodeURIComponent(run)}`;
  return topic ? `${path}/${encodeURIComponent(topic)}` : path;
}

/** Server-side read of a notes run, through the API's internal address. */
export async function fetchNotesRun(course: string, run: string): Promise<NotesRunView | null> {
  const res = await fetch(
    `${API_URL}/plans/${encodeURIComponent(course)}/notes/${encodeURIComponent(run)}`,
    { cache: "no-store" },
  );
  if (res.status === 404) return null;
  if (!res.ok) throw new ApiError(`Request failed (${res.status})`, res.status);
  return res.json();
}
