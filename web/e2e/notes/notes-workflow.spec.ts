import crypto from "node:crypto";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import {
  COURSE,
  attachDiagnostics,
  capture,
  mockRequests,
  notesUrl,
  stack,
  waitForRun,
  type RunView,
} from "./support";

// Task 12 (P3.3) workflow scenarios. Scenarios whose interfaces have not landed yet are
// `fixme` (skipped), never passing; see e2e/notes/README.md for their expectations.

const dependsOn = (...tasks: string[]) =>
  tasks.map((description) => ({ type: "depends-on", description }));

test.describe.configure({ mode: "serial" });
test.afterEach(async ({}, testInfo) => attachDiagnostics(testInfo));

type Block = { id: string; kind: string; title: string | null; content: string; citations: string[] };
type Topic = {
  topic_id: string;
  title: string;
  status: string;
  verification_stale: boolean;
  open_issues: { detail: string }[];
  blocks: Block[];
};
type Document = {
  language: string | null;
  assets: { id: string; path: string }[];
  sections: { topics: Topic[] }[];
};
type Head = { current_revision: number; document: Document; render: { id: string; status: string } | null };
type Revision = {
  revision: number;
  parent: number | null;
  origin: string;
  changed_topics: string[];
  restored_from: number | null;
};

// One generation for this file, separate from the smoke run, whose revision 0 stays intact.
let generation: Promise<RunView> | undefined;
async function generated(request: APIRequestContext): Promise<string> {
  generation ??= (async () => {
    const started = await request.post(`${stack.api}/plans/${COURSE}/notes`);
    expect(started.status(), await started.text()).toBe(202);
    return waitForRun(request, (await started.json()).run.id, 8 * 60_000);
  })();
  return (await generation).run.id;
}

async function head(request: APIRequestContext, run: string): Promise<Head> {
  const response = await request.get(notesUrl(run));
  expect(response.status()).toBe(200);
  return response.json();
}

async function revisions(request: APIRequestContext, run: string): Promise<Revision[]> {
  const response = await request.get(notesUrl(run, "/revisions"));
  expect(response.status()).toBe(200);
  return response.json();
}

async function revisionDocument(request: APIRequestContext, run: string, revision: number): Promise<Document> {
  const response = await request.get(notesUrl(run, `/revisions/${revision}`));
  expect(response.status()).toBe(200);
  return (await response.json()).document;
}

function topic(document: Document, id: string): Topic {
  const found = document.sections.flatMap((s) => s.topics).find((t) => t.topic_id === id);
  if (!found) throw new Error(`No topic ${id}`);
  return found;
}

const editor = (page: Page) => page.getByRole("region", { name: "Topic editor" });
const block = (page: Page, name: string) => editor(page).getByRole("region", { name, exact: true });
const content = (page: Page, name: string) =>
  block(page, name).getByLabel("Content (Markdown and LaTeX)");
const title = (page: Page, name: string) => block(page, name).getByLabel("Title", { exact: true });
const drafts = (page: Page) =>
  page.evaluate(() => Object.keys(sessionStorage).filter((key) => key.startsWith("kse-notes:draft:")));

async function openEditor(page: Page, run: string, topicId: string) {
  await page.goto(`/preview/${COURSE}/${run}/${topicId}`);
  await page.getByRole("tab", { name: "Edit" }).click();
  await expect(editor(page)).toBeVisible();
}

test("HTML → edit → save → new revision; a second tab gets 409 and recovers its draft", async ({
  context,
  page,
  request,
}) => {
  const run = await generated(request);
  const before = await head(request, run);
  const h = before.current_revision;
  const t1 = topic(before.document, "T1");
  const evidence = "linear-systems.md";
  const calls = mockRequests().length;

  // Tab A reads the rendered HTML, then edits; tab B starts its own draft from the same base.
  await page.goto(`/preview/${COURSE}/${run}/T1`);
  await expect(page.getByText(`Text revision ${h}`, { exact: true })).toBeVisible();
  await expect(page.getByText(/^HTML revision 0/)).toBeVisible();
  await expect(page.locator(`iframe[title="${t1.title}"]`)).toBeVisible();
  const tabB = await context.newPage();
  await openEditor(tabB, run, "T1");
  await title(tabB, "Block 1 (T1.1)").fill(`${t1.blocks[0].title} (B)`);
  await expect(editor(tabB).getByText("Unsaved draft")).toBeVisible();

  await page.getByRole("tab", { name: "Edit" }).click();
  await expect(editor(page).getByText(`Based on revision ${h}`, { exact: true })).toBeVisible();
  await expect(editor(page).getByText("No unsaved changes")).toBeVisible();

  // A formula, a new block moved up one place, and a citation from the evidence list.
  const sarrus = content(page, "Block 5 (T1.5)");
  const formula = (await sarrus.inputValue()).replace("\\det A =", "\\det(A) =");
  expect(formula).toContain("\\det(A) =");
  await sarrus.fill(formula);
  await expect(editor(page).getByText("Unsaved draft")).toBeVisible();
  await expect(editor(page).getByText(/kept in this browser tab only.*don't include it/)).toBeVisible();

  await editor(page).getByRole("button", { name: "Add block", exact: true }).click();
  const added = "Block 7 (new)";
  await block(page, added).getByRole("combobox", { name: "Kind" }).click();
  await page.getByRole("option", { name: "remark", exact: true }).click();
  await title(page, added).fill("Зауваження E2E");
  await content(page, added).fill("Коло: $x^2 + y^2 = r^2$.");
  await block(page, added).getByRole("button", { name: "Move block up" }).click();
  await expect(block(page, "Block 6 (new)")).toBeVisible();
  await expect(block(page, "Block 7 (T1.6)")).toBeVisible();
  const cite = block(page, "Block 7 (T1.6)").getByRole("checkbox", { name: new RegExp(evidence) });
  await expect(cite).not.toBeChecked();
  await cite.check();

  await editor(page).getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText(`Saved as revision ${h + 1}`)).toBeVisible();
  await expect(page.getByText(`Text revision ${h + 1}`, { exact: true })).toBeVisible();
  await expect(editor(page).getByText("No unsaved changes")).toBeVisible();
  await expect(editor(page).getByText("Verification outdated")).toBeVisible();
  await page.getByRole("tab", { name: "Preview" }).click();
  await expect(page.getByText(/^HTML revision \d+( · Older artifact)?/)).toBeVisible();

  const saved = await head(request, run);
  expect(saved.current_revision).toBe(h + 1);
  const edited = topic(saved.document, "T1");
  expect(edited.blocks.map((b) => b.id).slice(0, 5)).toEqual(t1.blocks.slice(0, 5).map((b) => b.id));
  expect(edited.blocks[4].content).toBe(formula);
  expect(edited.blocks[5]).toMatchObject({ kind: "remark", title: "Зауваження E2E", citations: [] });
  expect(edited.blocks[5].id).toMatch(/^b-[0-9a-f]{32}$/);
  expect(edited.blocks[6]).toMatchObject({ id: "T1.6", citations: ["6d546d06-0"] });
  expect(edited).toMatchObject({ status: "unresolved", verification_stale: true });
  expect(topic(saved.document, "T2")).toEqual(topic(before.document, "T2"));
  expect((await revisions(request, run)).at(-1)).toMatchObject({
    revision: h + 1,
    parent: h,
    origin: "manual",
    changed_topics: ["T1"],
  });
  expect(mockRequests().length, "a manual save calls no model").toBe(calls);

  // Browser Back reuses the cached T1 page; it must still show the saved revision.
  await page.getByRole("navigation", { name: "Topics" }).getByRole("link", { name: /T2/ }).click();
  await expect(page).toHaveURL(new RegExp(`/${run}/T2$`));
  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`/${run}/T1$`));
  await expect(page.getByText(`Text revision ${h + 1}`, { exact: true })).toBeVisible();
  await expect(page.getByText(/^HTML revision \d+( · Older artifact)?/)).toBeVisible();

  // Tab B: a background refresh shows the newer revision and keeps the draft as it is.
  await tabB.bringToFront();
  await tabB.evaluate(() => window.dispatchEvent(new Event("focus")));
  const stale = editor(tabB).getByRole("alert").filter({
    hasText: `Revision ${h + 1} was saved after this draft started`,
  });
  await expect(stale).toBeVisible();
  await expect(stale).toContainText(`based on revision ${h}`);
  await expect(title(tabB, "Block 1 (T1.1)")).toHaveValue(`${t1.blocks[0].title} (B)`);

  await editor(tabB).getByRole("button", { name: "Save changes" }).click();
  await expect(editor(tabB).getByRole("alert").filter({ hasText: "Not saved" })).toContainText(
    `current revision is ${h + 1}`,
  );
  await expect(title(tabB, "Block 1 (T1.1)")).toHaveValue(`${t1.blocks[0].title} (B)`);
  expect((await head(request, run)).current_revision).toBe(h + 1);

  // Reload: the draft is found under its original base, neither rebased nor hidden.
  await tabB.reload();
  await expect(tabB.getByRole("tab", { name: "Edit" })).toHaveAttribute("aria-selected", "true");
  await expect(title(tabB, "Block 1 (T1.1)")).toHaveValue(`${t1.blocks[0].title} (B)`);
  await expect(editor(tabB).getByText(`Based on revision ${h}`, { exact: true })).toBeVisible();
  expect(await drafts(tabB)).toEqual([expect.stringMatching(new RegExp(`/T1@${h}$`))]);
  const recovered = editor(tabB).getByRole("alert").filter({ hasText: "was saved after this draft started" });
  await recovered.getByRole("button", { name: `Show changes since revision ${h}` }).click();
  const since = recovered.getByRole("article", { name: /^Changed: Block 5 · example/ });
  await expect(since.locator("del", { hasText: "\\det A =" })).toBeVisible();
  await expect(since.locator("ins", { hasText: "\\det(A) =" })).toBeVisible();
  await expect(recovered.getByRole("article", { name: "Added: Block 6 · remark · Зауваження E2E" })).toBeVisible();

  // An explicit transfer makes the draft the new text of T1 on top of revision h+1.
  await recovered.getByRole("button", { name: `Transfer draft to revision ${h + 1}` }).click();
  await expect(recovered).toHaveCount(0);
  await expect(editor(tabB).getByText(`Based on revision ${h + 1}`, { exact: true })).toBeVisible();
  await editor(tabB).getByRole("button", { name: "Save changes" }).click();
  await expect(tabB.getByText(`Saved as revision ${h + 2}`)).toBeVisible();
  const transferred = topic((await head(request, run)).document, "T1");
  expect(transferred.blocks.map((b) => b.id)).toEqual(t1.blocks.map((b) => b.id));
  expect(transferred.blocks[0].title).toBe(`${t1.blocks[0].title} (B)`);
  expect(transferred.blocks[4].content).toBe(t1.blocks[4].content);
  expect(await drafts(tabB)).toEqual([]);
});

test("history diffs and restoring an earlier revision, seen from a new tab", async ({ context, page, request }) => {
  const run = await generated(request);
  const start = await head(request, run);
  const h = start.current_revision;
  const t2 = topic(start.document, "T2");
  const example = t2.blocks.findIndex((b) => b.kind === "example");
  const blocks = t2.blocks.map((b, i) =>
    i === example
      ? { ...b, content: `${b.content}\n\nПеревірка: $\\lambda_1 + \\lambda_2 = 4$.`, citations: [...b.citations, "6d546d06-0"] }
      : b,
  );
  // Precondition through the API: one saved T2 edit on top of the current revision.
  const edit = await request.patch(notesUrl(run, "/topics/T2"), { data: { base_revision: h, blocks } });
  expect(edit.status(), await edit.text()).toBe(200);
  expect((await edit.json()).revision.revision).toBe(h + 1);

  await page.goto(`/preview/${COURSE}/${run}/T2`);
  await page.getByRole("tab", { name: "History" }).click();
  const history = page.getByRole("region", { name: "Revision history" });
  const list = history.getByRole("list", { name: "Revisions" });
  await expect(list.getByRole("button")).toHaveCount((await revisions(request, run)).length);
  await expect(list.getByRole("button").first()).toContainText(new RegExp(`Revision ${h + 1}\\s*Current`));
  await expect(list.getByRole("button").first()).toContainText("Manual edit · T2");
  await expect(list.getByRole("button").last()).toContainText("Revision 0");
  await expect(list.getByRole("button").last()).toContainText("Generated");

  const changes = history.getByRole("region", { name: `Changes in revision ${h + 1}` });
  await expect(changes).toContainText(`Compared with revision ${h}.`);
  const changed = changes.getByRole("article", { name: new RegExp(`^Changed: Block ${example + 1} · example`) });
  await expect(changed.locator("ins", { hasText: "\\lambda_1 + \\lambda_2 = 4" })).toBeVisible();
  await expect(changed.locator("ins").filter({ hasText: "linear-systems.md" })).toBeVisible();
  await expect(changes.getByText(`${t2.blocks.length - 1} other blocks are unchanged.`)).toBeVisible();

  await list.getByRole("button", { name: new RegExp(`^Revision ${h}(?!\\d)`) }).click();
  await history.getByRole("button", { name: `Restore revision ${h}` }).click();
  const dialog = page.getByRole("dialog", { name: `Restore revision ${h}?` });
  await expect(dialog).toContainText(`gets the text of revision ${h} for T2`);
  const undone = dialog.getByRole("article", { name: new RegExp(`^Changed: Block ${example + 1}`) });
  await expect(undone.locator("del", { hasText: "\\lambda_1 + \\lambda_2 = 4" })).toBeVisible();
  await dialog.getByRole("button", { name: "Restore", exact: true }).click();
  await expect(page.getByText(`Restored revision ${h} as revision ${h + 2}`)).toBeVisible();
  await expect(page.getByText(`Text revision ${h + 2}`, { exact: true })).toBeVisible();
  await expect(list.getByRole("button").first()).toContainText(`Restored from revision ${h} · T2`);

  const restored = await head(request, run);
  expect(restored.current_revision).toBe(h + 2);
  expect((await revisions(request, run)).at(-1)).toMatchObject({
    revision: h + 2,
    parent: h + 1,
    origin: "restore",
    restored_from: h,
    changed_topics: ["T2"],
  });
  const t2Restored = topic(restored.document, "T2");
  expect(t2Restored.blocks).toEqual(topic(await revisionDocument(request, run, h), "T2").blocks);
  expect(t2Restored).toMatchObject({ status: "unresolved", verification_stale: true });
  expect(topic(restored.document, "T1")).toEqual(topic(start.document, "T1"));

  // A new tab loads the same state from the API: text revision, history and saved text.
  const fresh = await context.newPage();
  await fresh.goto(`/preview/${COURSE}/${run}/T2`);
  await expect(fresh.getByText(`Text revision ${h + 2}`, { exact: true })).toBeVisible();
  await expect(fresh.getByText("Verification outdated")).toBeVisible();
  await fresh.getByRole("tab", { name: "History" }).click();
  await expect(
    fresh.getByRole("list", { name: "Revisions" }).getByRole("button").first(),
  ).toContainText(new RegExp(`Revision ${h + 2}\\s*Current`));
  await fresh.getByRole("tab", { name: "Edit" }).click();
  await expect(content(fresh, `Block ${example + 1} (${t2.blocks[example].id})`)).toHaveValue(
    t2.blocks[example].content,
  );
});

test("leaving a topic with an unsaved draft asks first and keeps the draft", async ({ page, request }) => {
  const run = await generated(request);
  await openEditor(page, run, "T1");
  const field = content(page, "Block 1 (T1.1)");
  const text = `${await field.inputValue()}\n\nЧернетка, яку не збережено.`;
  await field.fill(text);

  const leave = page.getByRole("dialog", { name: "Leave with unsaved changes?" });
  const topics = page.getByRole("navigation", { name: "Topics" });
  await topics.getByRole("link", { name: /T2/ }).click();
  await expect(leave).toBeVisible();
  await expect(leave).toContainText("stays in this browser tab");
  await leave.getByRole("button", { name: "Stay" }).click();
  await expect(leave).toBeHidden();
  await expect(page).toHaveURL(new RegExp(`/${run}/T1$`));
  await expect(field).toHaveValue(text);

  await page.getByRole("link", { name: "KSE Notes" }).click();
  await expect(leave).toBeVisible();
  await leave.getByRole("button", { name: "Stay" }).click();
  await expect(page).toHaveURL(new RegExp(`/${run}/T1$`));

  // Closing or reloading the tab gets the browser's own prompt.
  const prompt = page.waitForEvent("dialog");
  await page.close({ runBeforeUnload: true });
  const unload = await prompt;
  expect(unload.type()).toBe("beforeunload");
  await unload.dismiss();
  expect(page.isClosed()).toBe(false);

  await topics.getByRole("link", { name: /T2/ }).click();
  await leave.getByRole("button", { name: "Leave" }).click();
  await expect(page).toHaveURL(new RegExp(`/${run}/T2$`));
  await expect(topics.getByRole("link", { name: /T1/ })).toContainText("Draft");
  await topics.getByRole("link", { name: /T1/ }).click();
  await expect(page.getByRole("tab", { name: "Edit" })).toHaveAttribute("aria-selected", "true");
  await expect(content(page, "Block 1 (T1.1)")).toHaveValue(text);
  await editor(page).getByRole("button", { name: "Discard draft" }).last().click();
  await page.getByRole("dialog", { name: "Discard your draft of T1?" }).getByRole("button", { name: "Discard" }).click();
  await expect(editor(page).getByText("No unsaved changes")).toBeVisible();
});

test("an uploaded figure goes into the local draft and is published by saving", async ({ page, request }) => {
  const run = await generated(request);
  const h = (await head(request, run)).current_revision;
  await openEditor(page, run, "T1");
  const target = "Block 6 (T1.6)";
  const dialog = page.getByRole("dialog", { name: "Insert an image into block 6" });

  await block(page, target).getByRole("button", { name: "Insert image" }).click();
  await expect(dialog.getByLabel("Label", { exact: true })).toHaveValue("fig-t1-1");
  await dialog.getByLabel(/^Image/).setInputFiles({
    name: "not-an-image.png",
    mimeType: "image/png",
    buffer: Buffer.from("plain text, not a PNG"),
  });
  await dialog.getByLabel("Caption").fill("Схема методу Гаусса");
  await dialog.getByRole("button", { name: "Upload and insert" }).click();
  await expect(dialog.getByRole("alert")).toContainText("Malformed, truncated or oversized image");

  await dialog.getByLabel(/^Image/).setInputFiles(path.join(stack.fixtures, "figure.png"));
  await dialog.getByRole("button", { name: "Upload and insert" }).click();
  await expect(dialog).toBeHidden();
  const figure = /!\[Схема методу Гаусса\]\((assets\/[0-9a-f]{64}\.png)\)\{#fig-t1-1\}$/;
  await expect(content(page, target)).toHaveValue(figure);
  expect((await head(request, run)).current_revision, "an upload commits nothing").toBe(h);

  await page.reload();
  await expect(content(page, target)).toHaveValue(figure);
  await editor(page).getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText(`Saved as revision ${h + 1}`)).toBeVisible();
  const saved = (await head(request, run)).document;
  const asset = figure.exec(topic(saved, "T1").blocks[5].content)?.[1];
  expect(saved.assets.map((a) => a.path)).toContain(asset);
});

test("notes with an unknown language need an explicit language before saving", async ({ page, request }) => {
  // A completed run whose document never recorded its language (not recoverable either).
  const run = `20261002-000000-${crypto.randomBytes(2).toString("hex")}`;
  const directory = path.join(stack.uploads, COURSE, "notes", run);
  const document = JSON.parse(fs.readFileSync(path.join(stack.fixtures, "control.json"), "utf8"));
  fs.mkdirSync(directory, { recursive: true });
  fs.writeFileSync(path.join(directory, "notes.json"), JSON.stringify({ ...document, run, language: null }));
  const stamp = "2026-10-02T00:00:00+00:00";
  fs.writeFileSync(
    path.join(directory, "run.json"),
    JSON.stringify({ id: run, course: COURSE, status: "done", stage: "done", created_at: stamp, updated_at: stamp, models: {} }),
  );
  expect((await head(request, run)).document.language).toBeNull();

  await openEditor(page, run, "T1");
  const save = editor(page).getByRole("button", { name: "Save changes" });
  await expect(editor(page).getByRole("combobox", { name: "Notes language" })).toBeVisible();
  await expect(editor(page).getByText("Choose the notes language to save.")).toBeVisible();
  await expect(save).toBeDisabled();
  await editor(page).getByRole("combobox", { name: "Notes language" }).click();
  await page.getByRole("option", { name: "Ukrainian (uk)" }).click();
  await expect(save).toBeEnabled();
  await save.click();
  await expect(page.getByText("Saved as revision 1")).toBeVisible();
  await expect(editor(page).getByRole("combobox", { name: "Notes language" })).toHaveCount(0);

  const saved = await head(request, run);
  expect(saved.document.language).toBe("uk");
  expect(topic(saved.document, "T1")).toMatchObject({ status: "verified", verification_stale: false });
  expect((await revisions(request, run)).at(-1)).toMatchObject({ revision: 1, origin: "manual", changed_topics: [] });
  await page.getByRole("tab", { name: "History" }).click();
  await expect(page.getByRole("list", { name: "Revisions" }).getByRole("button").first()).toContainText("Language set");
});

async function waitForRender(request: APIRequestContext, run: string, id: string) {
  let job: { status: string; errors: string[] };
  await expect.poll(async () => {
    const response = await request.get(notesUrl(run, `/render-jobs/${id}`));
    expect(response.status()).toBe(200);
    job = await response.json();
    return job.status;
  }, { timeout: 180_000, intervals: [500, 1000] }).toMatch(/^(done|failed)$/);
  return job!;
}

test("a delayed equal-text-revision response cannot regress completed artifacts", async ({ page, request }) => {
  const run = await generated(request);
  const before = await head(request, run);
  const blocks = structuredClone(topic(before.document, "T1").blocks);
  blocks[0].content += "\n\nRender response ordering.";
  const saved = await request.patch(notesUrl(run, "/topics/T1"), {
    data: { base_revision: before.current_revision, blocks },
  });
  expect(saved.status()).toBe(200);
  const pending = await (await request.get(notesUrl(run))).json();
  const done = await waitForRender(request, run, (await saved.json()).render.id);
  expect(done.status, done.errors.join("\n")).toBe("done");
  const revision = pending.current_revision;
  expect(pending.artifacts.some((a: { revision: number }) => a.revision < revision)).toBe(true);
  await page.goto(`/preview/${COURSE}/${run}/T1`);
  await page.waitForLoadState("networkidle");
  let release!: () => void;
  const held = new Promise<void>((resolve) => { release = resolve; });
  let arrived!: () => void;
  const waiting = new Promise<void>((resolve) => { arrived = resolve; });
  let count = 0;
  await page.route(notesUrl(run), async (route) => {
    if (count++ === 0) {
      arrived();
      await held;
      await route.fulfill({ json: pending, headers: { "Access-Control-Allow-Origin": "*" } });
    } else await route.continue();
  });
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await waiting;
  const fresh = page.waitForResponse(notesUrl(run));
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await fresh;
  await expect(page.getByText(`HTML revision ${revision}`, { exact: true })).toBeVisible();
  const old = page.waitForResponse(notesUrl(run));
  release();
  await (await old).finished();
  await page.waitForTimeout(500);
  // Wait for the delayed answer's React commit, then observe the user-visible revision.
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await expect(page.getByText(`HTML revision ${revision}`, { exact: true })).toBeVisible();
  await expect(page.getByText(/Older artifact:/)).toHaveCount(0);
});

test("saved and restored revisions get their own ready HTML/PDF artifacts", async ({ page, request }, testInfo) => {
  const run = await generated(request);
  const before = await head(request, run);
  if (before.render) await waitForRender(request, run, before.render.id);
  const calls = mockRequests().length;
  const h = before.current_revision;
  await openEditor(page, run, "T1");
  const target = "Block 6 (T1.6)";
  // Exercise the Task 7 image dialog with an empty block: figure is the first paragraph.
  await content(page, target).fill("");
  await content(page, target).click();
  await block(page, target).getByRole("button", { name: "Insert image" }).click();
  const dialog = page.getByRole("dialog", { name: "Insert an image into block 6" });
  const label = await dialog.getByLabel("Label", { exact: true }).inputValue();
  await dialog.getByLabel(/^Image/).setInputFiles(path.join(stack.fixtures, "figure.png"));
  await dialog.getByLabel("Caption").fill("Схема збереженої ревізії");
  await dialog.getByRole("button", { name: "Upload and insert" }).click();
  await expect(dialog).toBeHidden();
  const markdown = await content(page, target).inputValue();
  expect(markdown.trimStart()).toMatch(/^!\[/);
  await content(page, target).fill(`${markdown}\n\nДив. @${label}.`);
  await editor(page).getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText(`Saved as revision ${h + 1}`)).toBeVisible();
  await page.getByRole("tab", { name: "Preview", exact: true }).click();
  await expect(page.getByRole("status")).toContainText(`Rendering revision ${h + 1}`);
  const saved = await head(request, run);
  const done = await waitForRender(request, run, saved.render!.id);
  expect(done.status, done.errors.join("\n")).toBe("done");
  await expect(page.getByText(`HTML revision ${h + 1}`, { exact: true })).toBeVisible();
  const frame = page.frameLocator("iframe");
  await expect(frame.locator(`#${label} figure img`)).toBeVisible();
  await expect(frame.locator(`a.quarto-xref[href="#${label}"]`)).toContainText(/Рисунок\s*1/);
  await expect(frame.locator("body")).not.toContainText(`?@${label}`);
  await frame.locator(`#${label}`).scrollIntoViewIfNeeded();
  await capture(page, testInfo, "saved-revision-figure-first-html");
  await expect(page.locator("iframe")).toHaveAttribute("src", notesUrl(run, `/revisions/${h + 1}/topics/T1/artifacts/html`));
  const pdf = await request.get(notesUrl(run, `/revisions/${h + 1}/topics/T1/artifacts/pdf`));
  expect(pdf.status()).toBe(200);
  const bytes = await pdf.body();
  expect(bytes.subarray(0, 5).toString()).toBe("%PDF-");
  const extracted = spawnSync(path.resolve(stack.fixtures, "../../../.venv/bin/python"), ["-c",
    "import io,sys; from pypdf import PdfReader; print(' '.join(p.extract_text() for p in PdfReader(io.BytesIO(sys.stdin.buffer.read())).pages))"], { input: bytes, encoding: "utf8" });
  expect(extracted.status, extracted.stderr).toBe(0);
  expect(extracted.stdout).toContain("Схема збереженої ревізії");
  expect(extracted.stdout).toMatch(/Рисунок\s*1/);
  expect(extracted.stdout).not.toContain(`?@${label}`);

  const restored = await request.post(notesUrl(run, `/revisions/${h}/restore`), { data: { base_revision: h + 1 } });
  expect(restored.status()).toBe(200);
  const restoration = await restored.json();
  expect((await waitForRender(request, run, restoration.render.id)).status).toBe("done");
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByText(`Text revision ${h + 2}`, { exact: true })).toBeVisible();
  await expect(page.getByText(`HTML revision ${h + 2}`, { exact: true })).toBeVisible();
  expect(topic((await head(request, run)).document, "T1").blocks).toEqual(topic(before.document, "T1").blocks);

  const disabled = path.join(path.dirname(stack.uploads), "quarto-disabled");
  fs.writeFileSync(disabled, "disabled");
  try {
    await page.getByRole("tab", { name: "Edit", exact: true }).click();
    const text = await content(page, target).inputValue();
    await content(page, target).fill(`${text}\n\nSaved while Quarto is unavailable.`);
    await editor(page).getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByText(`Saved as revision ${h + 3}`)).toBeVisible();
    await expect(page.getByText(`Could not render revision ${h + 3}`, { exact: true })).toBeVisible();
    await page.getByRole("tab", { name: "Preview", exact: true }).click();
    await expect(page.getByText(new RegExp(`HTML revision ${h + 2} · Older artifact`))).toBeVisible();
    // The previous PDF stays available and is labelled with its own revision.
    await page.getByRole("button", { name: "PDF · Print" }).click();
    await expect(page.getByText(new RegExp(`PDF revision ${h + 2} · Older artifact`))).toBeVisible();
    await expect(page.locator("iframe")).toHaveAttribute("src", notesUrl(run, `/revisions/${h + 2}/topics/T1/artifacts/pdf`));
    await page.getByRole("button", { name: "HTML", exact: true }).click();
    const history: Revision[] = await (await request.get(notesUrl(run, "/revisions"))).json();
    expect(history.at(-1)).toMatchObject({ revision: h + 3, parent: h + 2, origin: "manual" });
    expect(topic((await head(request, run)).document, "T1").blocks[5].content).toContain("Saved while Quarto is unavailable.");
    expect((await request.get(notesUrl(run, `/revisions/${h + 3}/artifacts/pdf`))).status()).toBe(404);
    expect((await request.get(notesUrl(run, `/revisions/${h + 2}/artifacts/pdf`))).status()).toBe(200);
  } finally { fs.unlinkSync(disabled); }
  await page.getByRole("button", { name: "Retry render", exact: true }).click();
  await expect(page.getByText(`HTML revision ${h + 3}`, { exact: true })).toBeVisible({ timeout: 180_000 });
  await expect(page.getByText(/Older artifact:/)).toHaveCount(0);
  const currentPdf = await request.get(notesUrl(run, `/revisions/${h + 3}/artifacts/pdf`));
  expect((await currentPdf.body()).subarray(0, 5).toString()).toBe("%PDF-");
  expect(mockRequests().length, "save, restore and retry never call a model").toBe(calls);
});

type SuggestionRecord = { id: string; status: string; topic_id: string };

/** The worker's own records of suggestions: the one place that shows a rejected proposal. */
function suggestionRecords(run: string): SuggestionRecord[] {
  const folder = path.join(stack.uploads, COURSE, "notes", run, "suggestions");
  if (!fs.existsSync(folder)) return [];
  return fs.readdirSync(folder).map((name) => JSON.parse(fs.readFileSync(path.join(folder, name), "utf8")));
}

const schemaCount = (schema: string) => mockRequests().filter((call) => call.schema === schema).length;

test("AI suggestions are reviewed: reject, apply, stale conflict and a manual recheck", async ({ page, request }, testInfo) => {
  const run = await generated(request);
  const start = await head(request, run);
  if (start.render) await waitForRender(request, run, start.render.id);
  const h = start.current_revision;
  const before = topic(start.document, "T1");
  const otherBefore = topic(start.document, "T2");
  const history = (await revisions(request, run)).length;

  await openEditor(page, run, "T1");
  const ai = page.getByRole("region", { name: "AI suggestions" });
  const review = page.getByRole("region", { name: "Suggestion review" });
  const simpler = async (blockLabel: string) => {
    await ai.getByLabel(blockLabel).check();
    await ai.getByRole("button", { name: "Explain this more simply" }).click();
    await ai.getByRole("button", { name: "Request suggestion" }).click();
    await expect(review).toBeVisible({ timeout: 60_000 });
  };

  // Reject: the proposal is shown with its diff and a fresh check, and changes nothing.
  const suggestionCalls = schemaCount("topic_suggestion");
  const checkCalls = schemaCount("topic_verification");
  await simpler("Select block 6 (T1.6)");
  await expect(review).toContainText(`based on revision ${h}`);
  await expect(review.locator("ins", { hasText: "Простіше кажучи" })).toBeVisible();
  await expect(review).toContainText("Verified against the sources");
  expect(schemaCount("topic_suggestion")).toBe(suggestionCalls + 1);
  expect(schemaCount("topic_verification")).toBe(checkCalls + 1);
  expect((await head(request, run)).current_revision, "a proposal is not a revision").toBe(h);
  await capture(page, testInfo, "ai-suggestion-review");
  await review.getByRole("button", { name: "Reject suggestion" }).click();
  await expect(review).toHaveCount(0);
  expect(suggestionRecords(run).map((r) => r.status)).toEqual(["rejected"]);
  const rejected = await head(request, run);
  expect(rejected.current_revision).toBe(h);
  expect(topic(rejected.document, "T1")).toEqual(before);
  expect((await revisions(request, run)).length).toBe(history);

  // Ask again and apply: one new revision, and only the selected block of T1 changes.
  await simpler("Select block 6 (T1.6)");
  await review.getByRole("button", { name: "Apply suggestion" }).click();
  await expect(page.getByText(`Applied as revision ${h + 1}`)).toBeVisible();
  await expect(page.getByText(`Text revision ${h + 1}`, { exact: true })).toBeVisible();
  const applied = await head(request, run);
  expect(applied.current_revision).toBe(h + 1);
  expect((await revisions(request, run)).at(-1)).toMatchObject({
    revision: h + 1,
    parent: h,
    origin: "ai",
    changed_topics: ["T1"],
  });
  const edited = topic(applied.document, "T1");
  expect(edited.blocks.map((b) => b.id)).toEqual(before.blocks.map((b) => b.id));
  expect(edited.blocks.slice(0, 5)).toEqual(before.blocks.slice(0, 5));
  expect(edited.blocks[5].content).toContain("Простіше кажучи");
  expect(edited).toMatchObject({ status: "verified", verification_stale: false });
  expect(topic(applied.document, "T2")).toEqual(otherBefore);
  expect(suggestionRecords(run).map((r) => r.status).sort()).toEqual(["applied", "rejected"]);
  // The applied revision gets its own real files, with the suggested text.
  const render = await waitForRender(request, run, applied.render!.id);
  expect(render.status, render.errors.join("\n")).toBe("done");
  const html = await request.get(notesUrl(run, `/revisions/${h + 1}/topics/T1/artifacts/html`));
  expect(html.status()).toBe(200);
  expect(await html.text()).toContain("Простіше кажучи");
  const pdf = await request.get(notesUrl(run, `/revisions/${h + 1}/topics/T1/artifacts/pdf`));
  expect((await pdf.body()).subarray(0, 5).toString()).toBe("%PDF-");

  // An example is inserted right after the selected block, with a server-assigned ID.
  await ai.getByLabel("Select block 6 (T1.6)").uncheck();
  await ai.getByLabel("Select block 5 (T1.5)").check();
  await ai.getByRole("button", { name: "Expand the example with a worked case" }).click();
  await ai.getByRole("button", { name: "Request suggestion" }).click();
  await expect(review).toBeVisible({ timeout: 60_000 });
  await expect(review.getByRole("article", { name: /^Added: Block 6 · example/ })).toBeVisible();
  await review.getByRole("button", { name: "Apply suggestion" }).click();
  await expect(page.getByText(`Applied as revision ${h + 2}`)).toBeVisible();
  const expanded = topic((await head(request, run)).document, "T1");
  expect(expanded.blocks.length).toBe(before.blocks.length + 1);
  expect(expanded.blocks[4].id).toBe("T1.5");
  expect(expanded.blocks[5].id).toMatch(/^b-[0-9a-f]{32}$/);
  expect(expanded.blocks[5].content).toContain("x = y = 1");
  expect(expanded.blocks[6]).toEqual(edited.blocks[5]);

  // Stale: the notes move on while a suggestion is on screen. It is never applied.
  // A different block: the mock would repeat the summary's text, which changes nothing.
  await simpler("Select block 4 (T1.4)");
  const t2 = structuredClone(topic((await head(request, run)).document, "T2").blocks);
  t2[0].content += "\n\nПримітка після пропозиції.";
  const moved = await request.patch(notesUrl(run, "/topics/T2"), { data: { base_revision: h + 2, blocks: t2 } });
  expect(moved.status(), await moved.text()).toBe(200);
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(review.getByText("The notes changed after this suggestion")).toBeVisible();
  await expect(review.getByRole("button", { name: "Apply suggestion" })).toBeDisabled();
  const pending = suggestionRecords(run).find((r) => r.status === "ready")!;
  const refused = await request.post(notesUrl(run, `/suggestions/${pending.id}/apply`), { data: { base_revision: h + 2 } });
  expect(refused.status()).toBe(409);
  expect((await head(request, run)).current_revision, "a stale apply creates nothing").toBe(h + 3);
  await review.getByRole("button", { name: "Reject suggestion" }).click();
  await expect(review).toHaveCount(0);
  expect(topic((await head(request, run)).document, "T1")).toEqual(expanded);

  // Manual recheck: T2 is unresolved for real (the mock finds a major issue every time).
  const t2Before = topic((await head(request, run)).document, "T2");
  await openEditor(page, run, "T2");
  const checks = schemaCount("topic_verification");
  await ai.getByRole("button", { name: "Verify this topic again" }).click();
  const result = page.getByRole("group", { name: "Verification result" });
  await expect(result).toBeVisible({ timeout: 60_000 });
  await expect(result).toContainText("Not verified");
  await expect(result).toContainText("Синтетичні джерела не містять спектральної теореми.");
  expect(schemaCount("topic_verification")).toBeGreaterThan(checks);
  const checked = await head(request, run);
  expect(checked.current_revision).toBe(h + 4);
  expect((await revisions(request, run)).at(-1)).toMatchObject({
    revision: h + 4,
    parent: h + 3,
    origin: "verification",
    changed_topics: ["T2"],
  });
  const t2After = topic(checked.document, "T2");
  expect(t2After.blocks).toEqual(t2Before.blocks);
  expect(t2After).toMatchObject({ status: "unresolved", verification_stale: false });
  expect(t2After.open_issues.map((i) => i.detail)).toContain(
    "Синтетичні джерела не містять спектральної теореми.",
  );
  expect((await waitForRender(request, run, checked.render!.id)).status).toBe("done");
});

const DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

test("Word is prepared on demand for one revision and downloads with its figure and contents", async ({
  page,
  request,
}, testInfo) => {
  const run = await generated(request);
  const before = await head(request, run);
  if (before.render) await waitForRender(request, run, before.render.id);
  const calls = mockRequests().length;
  const h = before.current_revision;

  // A figure in T2 through the real asset route; the generated notes have none of their own.
  const upload = await request.post(notesUrl(run, "/assets"), {
    multipart: {
      file: { name: "figure.png", mimeType: "image/png", buffer: fs.readFileSync(path.join(stack.fixtures, "figure.png")) },
    },
  });
  expect(upload.status(), await upload.text()).toBe(201);
  const figure = (await upload.json()).markdown_path as string;
  const edit = async (base: number, extra: string) => {
    const blocks = structuredClone(topic((await head(request, run)).document, "T2").blocks);
    blocks[0].content += extra;
    const saved = await request.patch(notesUrl(run, "/topics/T2"), { data: { base_revision: base, blocks } });
    expect(saved.status(), await saved.text()).toBe(200);
    const job = await waitForRender(request, run, (await saved.json()).render.id);
    expect(job.status, job.errors.join("\n")).toBe("done");
  };
  await edit(h, `\n\n![Схема для Word](${figure}){#fig-t2-word}\n\nДив. @fig-t2-word.`);

  await page.goto(`/preview/${COURSE}/${run}`);
  await expect(page.getByText(`Text revision ${h + 1}`, { exact: true })).toBeVisible();
  const word = page.getByRole("group", { name: "Word" });
  await expect(word.getByRole("link", { name: /Download Word/ })).toHaveCount(0);
  await word.getByRole("button", { name: "Prepare Word" }).click();
  await expect(word.getByRole("button", { name: "Preparing Word…" })).toBeDisabled();
  const link = word.getByRole("link", { name: /^Download Word/ });
  await expect(link).toBeVisible({ timeout: 120_000 });
  await expect(link).toContainText(`rev. ${h + 1}`);
  await capture(page, testInfo, "word-ready");

  const [download] = await Promise.all([page.waitForEvent("download"), link.click()]);
  expect(download.suggestedFilename()).toBe("notes.docx");
  const file = await download.path();
  const unpacked = spawnSync(path.resolve(stack.fixtures, "../../../.venv/bin/python"), ["-c",
    "import json,sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); print(json.dumps({'names': z.namelist(), 'xml': z.read('word/document.xml').decode()}))", file], { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  expect(unpacked.status, unpacked.stderr).toBe(0);
  const docx = JSON.parse(unpacked.stdout) as { names: string[]; xml: string };
  expect(docx.names.some((name) => /^word\/media\/.+\.png$/.test(name)), "the figure is embedded").toBe(true);
  for (const text of ["Схема для Word", "Власні значення та власні вектори", "Рисунок"]) expect(docx.xml).toContain(text);
  // A static, linked contents list instead of a field that stays empty until Word updates it.
  expect(docx.xml).toContain("Зміст");
  expect(docx.xml).toContain('w:anchor="sec-T2"');
  expect(docx.xml).not.toMatch(/TOC \\/);
  expect(docx.xml).toContain("<m:oMath>");
  expect(docx.xml).not.toContain("?@");

  const served = await request.get(notesUrl(run, `/revisions/${h + 1}/artifacts/docx`));
  expect(served.status()).toBe(200);
  expect(served.headers()["content-type"]).toBe(DOCX);
  expect(served.headers()["x-notes-revision"]).toBe(String(h + 1));

  // A newer revision gets no Word file until asked: the old one is labelled, not offered as current.
  await edit(h + 1, "\n\nПісля Word.");
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByText(`Text revision ${h + 2}`, { exact: true })).toBeVisible();
  await expect(word.getByRole("link", { name: /^Download Word/ })).toHaveCount(0);
  await expect(word.getByRole("link", { name: `Older Word file · revision ${h + 1}` })).toBeVisible();
  expect((await request.get(notesUrl(run, `/revisions/${h + 2}/artifacts/docx`))).status()).toBe(404);

  // A failed Word job keeps HTML and PDF, says so, and Retry publishes the file.
  const disabled = path.join(path.dirname(stack.uploads), "quarto-disabled");
  fs.writeFileSync(disabled, "disabled");
  try {
    await word.getByRole("button", { name: "Prepare Word" }).click();
    await expect(page.getByText(`Could not prepare Word for revision ${h + 2}`, { exact: true })).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText("Your saved text, HTML and PDF are kept.")).toBeVisible();
    await expect(page.getByText(`HTML revision ${h + 2}`, { exact: true })).toBeVisible();
    await expect(word.getByRole("link", { name: /^Download Word/ })).toHaveCount(0);
    expect((await request.get(notesUrl(run, `/revisions/${h + 2}/artifacts/html`))).status()).toBe(200);
    expect((await request.get(notesUrl(run, `/revisions/${h + 2}/artifacts/docx`))).status()).toBe(404);
  } finally {
    fs.rmSync(disabled, { force: true });
  }
  await word.getByRole("button", { name: "Retry Word" }).click();
  await expect(word.getByRole("link", { name: /^Download Word/ })).toContainText(`rev. ${h + 2}`, { timeout: 120_000 });
  await expect(page.getByText(`Could not prepare Word for revision ${h + 2}`)).toHaveCount(0);
  expect((await request.get(notesUrl(run, `/revisions/${h + 2}/artifacts/docx`))).status()).toBe(200);
  expect(mockRequests().length, "Word makes no model calls").toBe(calls);
});

test.fixme(
  "Course book search from one revision",
  {
    annotation: dependsOn("Task 11 / P3.2: book render job, GET .../revisions/{revision}/book/{asset_path}"),
  },
  async () => {},
);
