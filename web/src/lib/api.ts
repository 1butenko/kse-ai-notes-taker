import { tabSession } from "@/lib/session";

export const API_URL = process.env.API_URL ?? "http://localhost:8000";

export const PUBLIC_API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? `http://localhost:${process.env.API_PORT}`;

const SESSION_HEADER = "x-session";

function withSession(url: string, session = tabSession()): string {
  return `${url}${url.includes("?") ? "&" : "?"}session=${encodeURIComponent(session)}`;
}

export function endTabSession() {
  navigator.sendBeacon(withSession(`${PUBLIC_API_URL}/session/end`));
}

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

export class ApiError extends Error {}

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
  const headers = new Headers(init?.headers);
  headers.set(SESSION_HEADER, tabSession());
  const res = await fetch(`${PUBLIC_API_URL}${path}`, { ...init, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : `Request failed (${res.status})`;
    throw new ApiError(detail);
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

export function uploadMoodleLinks(courseId: number, modules: number[]): Promise<SavedFile[]> {
  return request("/uploads/moodle/links", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ course_id: courseId, modules }),
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
  const url = withSession(`${PUBLIC_API_URL}/files?path=${encodeURIComponent(path)}`);
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
  topic_id: string;
  title: string;
  status: TopicStatus;
  blocks: NoteBlock[];
  evidence: EvidenceItem[];
  rounds: number;
  verifier: string | null;
  open_issues: VerificationIssue[];
  error: string | null;
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

export type NotesDocument = {
  course: string;
  run: string;
  title: string;
  created_at: string;
  sections: { title: string; topics: TopicNote[] }[];
  sources: NotesSource[];
  models: Record<string, string>;
};

export type NotesRunView = {
  run: NotesRun;
  document: NotesDocument | null;
  pdf: boolean;
  topic_pdfs: string[];
};

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

export function notesFileUrl(
  course: string,
  run: string,
  kind: "pdf" | "qmd",
  session?: string,
): string {
  return withSession(`${PUBLIC_API_URL}/plans/${course}/notes/${run}/${kind}`, session);
}

export function topicPdfUrl(course: string, run: string, topic: string, session?: string): string {
  return withSession(
    `${PUBLIC_API_URL}/plans/${course}/notes/${run}/topics/${encodeURIComponent(topic)}/pdf`,
    session,
  );
}

export function previewPath(course: string, run: string, topic?: string, session?: string): string {
  const path = `/preview/${encodeURIComponent(course)}/${encodeURIComponent(run)}`;
  return withSession(topic ? `${path}/${encodeURIComponent(topic)}` : path, session);
}

/** Server-side read of a notes run, through the API's internal address. */
export async function fetchNotesRun(
  course: string,
  run: string,
  session: string,
): Promise<NotesRunView | null> {
  const res = await fetch(
    `${API_URL}/plans/${encodeURIComponent(course)}/notes/${encodeURIComponent(run)}`,
    { cache: "no-store", headers: { [SESSION_HEADER]: session } },
  );
  if (res.status === 404) return null;
  if (!res.ok) throw new ApiError(`Request failed (${res.status})`);
  return res.json();
}
