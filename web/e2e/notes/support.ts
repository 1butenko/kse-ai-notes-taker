import fs from "node:fs";
import path from "node:path";

import type { APIRequestContext, Locator, Page, TestInfo } from "@playwright/test";

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is not set; run through \`npm run test:e2e:notes\``);
  return value;
}

export const stack = {
  api: required("NOTES_E2E_API_URL"),
  uploads: required("NOTES_E2E_UPLOADS"),
  logs: required("NOTES_E2E_LOGS"),
  fixtures: required("NOTES_E2E_FIXTURES"),
};

export const COURSE = "local";
export const LEGACY_RUN = "20261001-000000-0001";

type Control = {
  title: string;
  assets: { id: string; path: string }[];
  sections: { title: string; topics: { topic_id: string; title: string }[] }[];
};

export const control: Control = JSON.parse(
  fs.readFileSync(path.join(stack.fixtures, "control.json"), "utf8"),
);

export type Artifact = {
  format: string;
  path: string;
  revision: number;
  status: "ready" | "failed";
  error: string | null;
  topic_id: string | null;
};

export type RunView = {
  run: {
    id: string;
    status: "queued" | "running" | "done" | "failed";
    stage: string;
    error: string | null;
    warnings: string[];
    events: { at: string; stage: string; message: string }[];
  };
  document: {
    schema_version: number;
    language: string | null;
    title: string;
    sections: {
      topics: { topic_id: string; status: string; open_issues: unknown[]; blocks: unknown[] }[];
    }[];
  } | null;
  artifacts: Artifact[];
};

export function notesUrl(run: string, suffix = ""): string {
  return `${stack.api}/plans/${COURSE}/notes/${run}${suffix}`;
}

/** Poll the real run until the worker finishes; a failed run stops the test at once. */
export async function waitForRun(
  request: APIRequestContext,
  run: string,
  timeoutMs: number,
): Promise<RunView> {
  const deadline = Date.now() + timeoutMs;
  let view: RunView | undefined;
  while (Date.now() < deadline) {
    const response = await request.get(notesUrl(run));
    if (!response.ok()) throw new Error(`GET run ${run}: ${response.status()} ${await response.text()}`);
    view = (await response.json()) as RunView;
    if (view.run.status === "failed") {
      throw new Error(`Run ${run} failed at ${view.run.stage}: ${view.run.error}`);
    }
    if (view.run.status === "done") return view;
    await new Promise((resolve) => setTimeout(resolve, 1_000));
  }
  throw new Error(
    `Run ${run} still ${view?.run.status}/${view?.run.stage} after ${timeoutMs / 1000}s`,
  );
}

export function mockRequests(): { schema?: string; model?: string; topic?: string; error?: string }[] {
  const file = path.join(stack.logs, "openrouter.jsonl");
  if (!fs.existsSync(file)) return [];
  return fs
    .readFileSync(file, "utf8")
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

function files(directory: string, match: (name: string) => boolean): string[] {
  if (!fs.existsSync(directory)) return [];
  return fs.readdirSync(directory, { recursive: true, encoding: "utf8" })
    .filter((name) => match(path.basename(name)) && fs.statSync(path.join(directory, name)).isFile())
    .map((name) => path.join(directory, name));
}

/** On failure: server logs, the mock LLM log, run state and Quarto logs of every run. */
export async function attachDiagnostics(testInfo: TestInfo): Promise<void> {
  if (testInfo.status === testInfo.expectedStatus) return;
  for (const file of files(stack.logs, (name) => /\.(log|jsonl)$/.test(name))) {
    await testInfo.attach(`logs/${path.basename(file)}`, { path: file, contentType: "text/plain" });
  }
  const notes = path.join(stack.uploads, COURSE, "notes");
  for (const file of files(notes, (name) => name === "run.json" || name === "artifacts.json" || /^quarto-(html|pdf|docx|book)\.log$/.test(name))) {
    await testInfo.attach(`runs/${path.relative(notes, file)}`, { path: file, contentType: "text/plain" });
  }
}

/** Saved on every run for visual QA; a page shot shows only the frame's visible part. */
export async function capture(
  target: Page | Locator,
  testInfo: TestInfo,
  name: string,
): Promise<void> {
  const file = testInfo.outputPath(`${name}.png`);
  if ("goto" in target) await target.screenshot({ path: file, fullPage: true });
  else await target.screenshot({ path: file });
  await testInfo.attach(name, { path: file, contentType: "image/png" });
}
