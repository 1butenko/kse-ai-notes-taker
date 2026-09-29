export const API_URL = process.env.API_URL ?? "http://localhost:8000";

export const PUBLIC_API_URL = `http://localhost:${process.env.API_PORT}`;

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
  const res = await fetch(`${PUBLIC_API_URL}${path}`, init);
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

export type SessionView = {
  id: string;
  session: Session;
  files: SavedFile[];
};

export type PlanView = {
  course: string;
  primary: string | null;
  transcript: Transcript | null;
  sessions: SessionView[];
  unassigned: SavedFile[];
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
