/** The API as the signed-in teacher: the web's own route handler (src/app/api/[...path]). */
const API_BASE = "/api";

/** The API itself, for what needs no sign-in: published lecture-notes pages. */
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
  /** The response's `detail` when it isn't a message, e.g. a list of problems. */
  readonly detail: unknown;

  constructor(message: string, status = 0, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

export type UploadCategory = "syllabus" | "reading";

export type SavedFile = {
  path: string;
  size: number;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (res.status === 401 && typeof window !== "undefined") {
    // The session ended: sign in again, then come back here.
    const back = window.location.pathname + window.location.search;
    // A full page load, not the router: the server must read the new session cookie.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.href = `/sign-in?callbackUrl=${encodeURIComponent(back)}`;
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : `Request failed (${res.status})`;
    throw new ApiError(detail, res.status, body?.detail);
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

/** Saves the lecturer's edits to a stored transcript: renamed, removed or added sessions. */
export function saveTranscript(path: string, transcript: Transcript): Promise<Transcript> {
  return request(`/syllabus/transcript?path=${encodeURIComponent(path)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(transcript),
  });
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

export type FileView = Omit<SavedFile, "size"> & {
  /** Null for an excerpt: its pages are cut from the book when opened. */
  size: number | null;
  excerpt: Excerpt | null;
  /** Uploaded for this lecture only: not a course reading, never matched to other lectures. */
  lecture_only?: boolean;
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
  /** Fingerprint of this lecture's readings; a lecture run records the one it used. */
  materials: string;
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
  /** Fingerprint of the files attached to the sessions; a run records the one it used. */
  materials: string;
};

export function courseKey(courseId?: number): string {
  return courseId ? String(courseId) : "local";
}

export type CourseInfo = {
  course: string;
  name: string;
  created_at: string;
  /** When the lecturer approved the readings per lecture; cleared by reading the lectures anew. */
  readings_approved_at?: string | null;
};

/** The caller's role on a course: a member's, or an admin's (a lecturer's rights everywhere). */
export type CourseRole = "lecturer" | "ta" | "admin";

/** A course in the list, with the caller's role on it. */
export type CourseListItem = CourseInfo & { role: CourseRole };

/** The signed-in teacher's courses (every course for an admin), newest first. */
export function listCourseInfo(): Promise<CourseListItem[]> {
  return request("/course-info");
}

export type TeamMember = {
  email: string;
  role: "lecturer" | "ta";
  /** Empty until they have signed in. */
  name: string;
  signed_in: boolean;
  avatar_url: string | null;
  added_at: string;
};

export type Team = {
  my_role: CourseRole;
  members: TeamMember[];
};

export type CourseEvent = {
  id: string;
  kind:
    | "material_uploaded"
    | "material_deleted"
    | "moodle_synced"
    | "notes_generated"
    | "readings_approved"
    | "readings_approval_revoked"
    | "member_added"
    | "member_removed"
    | "lecturer_changed"
    | "course_started_over";
  details: Record<string, unknown>;
  at: string;
  /** null: the worker, or something that happened before the log existed. */
  actor_email: string | null;
  actor_name: string | null;
};

/** The course's members and the caller's role. */
export function getTeam(course: string): Promise<Team> {
  return request(`/team/${course}`);
}

/** Add a TA by email (lecturer or admin). */
export function addTeamMember(course: string, email: string): Promise<Team> {
  return request(`/team/${course}/members`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
}

export function removeTeamMember(course: string, email: string): Promise<Team> {
  return request(`/team/${course}/members?email=${encodeURIComponent(email)}`, {
    method: "DELETE",
  });
}

/** Make someone the lecturer; the previous lecturer stays on as a TA. */
export function setLecturer(course: string, email: string): Promise<Team> {
  return request(`/team/${course}/lecturer`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
}

/** Who did what on the course, newest first. */
export function getCourseActivity(course: string): Promise<CourseEvent[]> {
  return request(`/team/${course}/activity`);
}

export function saveCourseInfo(course: string, name: string): Promise<CourseInfo> {
  return request(`/course-info/${course}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export function getCourseInfo(course: string): Promise<CourseInfo> {
  return request(`/course-info/${course}`);
}

export function approveReadings(course: string): Promise<CourseInfo> {
  return request(`/course-info/${course}/readings-approval`, { method: "POST" });
}

/** Moves the course (files, plan, transcripts) to the server trash. */
export function deleteCourse(course: string): Promise<void> {
  return request(`/course-info/${course}`, { method: "DELETE" });
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

/** Files for one lecture only: stored under the lecture and attached to it. */
export function uploadLectureFiles(
  course: string,
  sessionId: string,
  files: File[],
): Promise<PlanView> {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  return request(`/plans/${course}/sessions/${sessionId}/lecture-files`, {
    method: "POST",
    body: form,
  });
}

export function dismissUnassigned(course: string, path: string): Promise<PlanView> {
  return request(`/plans/${course}/unassigned?path=${encodeURIComponent(path)}`, {
    method: "DELETE",
  });
}

export function fileName(path: string): string {
  return path.split("/").pop() ?? path;
}

/** Whether a file opens as a PDF. An excerpt has no extension: its pages are cut from a book. */
export function isPdfPath(path: string): boolean {
  return /\.pdf$/i.test(path) || path.split("/")[1] === "excerpts";
}

export function fileUrl(path: string, page?: number): string {
  const url = `${API_BASE}/files?path=${encodeURIComponent(path)}`;
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

export function lecturePath(course: string, sessionId: string): string {
  return `/lectures/${encodeURIComponent(course)}/${encodeURIComponent(sessionId)}`;
}

// The AI Note Taker: Moodle materials fetched by the agent into S3 (`/agent/courses`).

export type AgentMaterial = {
  id: string;
  name: string;
  mimetype: string;
  size: number;
  reason: string;
  /** A temporary S3 download link. */
  url: string;
};

export type AgentTopic = {
  section: number;
  name: string;
  summary: string;
  materials: AgentMaterial[];
};

export type AgentTodo = {
  content: string;
  status: "pending" | "in_progress" | "completed";
};

export type AgentAction = {
  text: string;
  status: "running" | "done" | "failed";
  detail: string;
  /** The todo in progress when the action started; missing on older runs. */
  todo?: string | null;
};

export type AgentRun = {
  id: string;
  status: "running" | "succeeded" | "failed";
  focus: string | null;
  /** What the agent is doing right now. */
  step: string | null;
  /** The agent's todo list, as it keeps it. */
  todos: AgentTodo[];
  /** Its latest actions, oldest first. */
  actions: AgentAction[];
  report: string | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
};

export type AgentCourse = {
  id: string;
  course_key: string;
  title: string;
  moodle_course_id: number;
  materials: number;
  topics: AgentTopic[];
  latest_run: AgentRun | null;
};

/** The course's fetched materials and latest run; a 404 means the agent never ran for it. */
export function getAgentCourse(course: string): Promise<AgentCourse> {
  return request(`/agent/courses/${course}`, { cache: "no-store" });
}

// Visual lecture notes: the lecture-notes agent writes one lecture as a Quarto page
// (`/lecture-notes`).

export type LectureNotesRun = {
  id: string;
  session_id: string;
  session_label: string;
  status: "running" | "succeeded" | "failed" | "cancelled";
  step: string | null;
  todos: AgentTodo[];
  actions: AgentAction[];
  report: string | null;
  error: string | null;
  /** The published page's files; `index.html` is the page. */
  files: string[];
  model: string | null;
  renders: number;
  /** The lecture's readings changed since this run read them. */
  readings_changed: boolean;
  /** `agent`: written by the model; `edit`: a teacher's edit of the `edited_from` run. */
  kind: "agent" | "edit";
  edited_from: string | null;
  started_at: string;
  finished_at: string | null;
};

/** One lecture's notes: its latest run, and the latest that published a page. */
export type LectureNotesStatus = {
  session_id: string;
  latest: LectureNotesRun;
  published: LectureNotesRun | null;
};

/** Every lecture with notes (or a run) in the course. */
export function listCourseLectureNotes(course: string): Promise<LectureNotesStatus[]> {
  return request(`/lecture-notes/${encodeURIComponent(course)}/runs`, { cache: "no-store" });
}

function lectureNotesPath(course: string, sessionId: string): string {
  return `/lecture-notes/${encodeURIComponent(course)}/${encodeURIComponent(sessionId)}/runs`;
}

/** The lecture's visual-notes runs, newest first. */
export function listLectureNotes(course: string, sessionId: string): Promise<LectureNotesRun[]> {
  return request(lectureNotesPath(course, sessionId), { cache: "no-store" });
}

export function startLectureNotes(course: string, sessionId: string): Promise<LectureNotesRun> {
  return request(lectureNotesPath(course, sessionId), { method: "POST" });
}

export function cancelLectureNotes(run: string): Promise<LectureNotesRun> {
  return request(`/lecture-notes/runs/${encodeURIComponent(run)}/cancel`, { method: "POST" });
}

/** The published page, for a sandboxed iframe or a new tab. The page used to be served as
 * immutable for a year; a re-render replaces it, so `?v=2` is a new address that browsers holding
 * the old copy fetch afresh. The API ignores the query and now serves the page `no-cache`. */
export function lectureNotesSiteUrl(run: string, file = "index.html"): string {
  const version = file === "index.html" ? "?v=2" : "";
  return `${PUBLIC_API_URL}/lecture-notes/runs/${encodeURIComponent(run)}/site/${file}${version}`;
}

/** A published version's Quarto body, for the editor. */
export type LectureNotesSource = {
  run_id: string;
  body: string;
  /** Its SVG figures, `assets/<name>.svg`, served next to its page. */
  assets: string[];
  /** Citation keys (`r1`) and the readings they stand for. */
  references: { id: string; title: string }[];
};

export function getLectureNotesSource(run: string): Promise<LectureNotesSource> {
  return request(`/lecture-notes/runs/${encodeURIComponent(run)}/source`, { cache: "no-store" });
}

/** One problem the note checker found in an edit; `line` is 0 for the whole note. */
export type NoteIssue = { line: number; message: string };

/** Save an edit of the published notes; poll the returned run, which replaces them once it is
 * rendered (the server keeps each save as a run of its own). A 422
 * `ApiError` carries the checker's `NoteIssue[]` as its `detail`. */
export function saveLectureNotesEdit(
  run: string,
  body: string,
  assets: Record<string, string> = {},
): Promise<LectureNotesRun> {
  return request(`/lecture-notes/runs/${encodeURIComponent(run)}/edits`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body, assets }),
  });
}

/** The editor of a lecture's notes: it opens the newest published ones. */
export function editNotesPath(course: string, sessionId: string): string {
  return `${lecturePath(course, sessionId)}/edit`;
}

/** A lecture's notes: the newest published ones. With `saving`, the run of a save being
 * rendered, shown until it is published. */
export function visualNotesPath(course: string, sessionId: string, saving?: string): string {
  const path = `${lecturePath(course, sessionId)}/visual`;
  return saving ? `${path}/${encodeURIComponent(saving)}` : path;
}

/** Starts the AI Note Taker for a course created from Moodle; poll `getAgentCourse`. */
export function startAgentSync(course: string, focus?: string): Promise<AgentRun> {
  return request(`/agent/courses/${course}/sync`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ focus: focus?.trim() || null }),
  });
}

export type Me = {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  avatar_url: string | null;
};

export function getMe(): Promise<Me> {
  return request("/me");
}

export function updateMe(names: { first_name: string; last_name: string }): Promise<Me> {
  return request("/me", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(names),
  });
}
