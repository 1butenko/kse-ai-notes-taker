import fs from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { attachDiagnostics, capture, control, mockRequests, notesUrl, stack } from "./support";

test.afterEach(async ({}, info) => attachDiagnostics(info));

const RUN = "20261026-000000-a551";

function seedControlRun() {
  const document = structuredClone(control) as typeof control & {
    run: string;
    assets: { id: string; path: string; sha256: string }[];
  };
  document.run = RUN;
  const folder = path.join(stack.uploads, "local", "notes", RUN);
  fs.mkdirSync(folder, { recursive: true });
  fs.writeFileSync(path.join(folder, "notes.json"), JSON.stringify(document));
  fs.writeFileSync(path.join(folder, "run.json"), JSON.stringify({
    id: RUN, course: "local", status: "done", stage: "done",
    created_at: "2026-10-26T00:00:00Z", updated_at: "2026-10-26T00:00:00Z",
    models: {}, topics_total: 2, topics_done: 2, warnings: [], error: null, events: [],
  }));
  return document;
}

test("teacher approves unresolved saved text, revokes it, and records audit without model calls", async ({ context, page, request }, testInfo) => {
  const document = seedControlRun();
  const upload = await request.post(notesUrl(RUN, "/assets"), {
    multipart: { file: { name: "figure.png", mimeType: "image/png", buffer: fs.readFileSync(path.join(stack.fixtures, "figure.png")) } },
  });
  expect(upload.status(), await upload.text()).toBe(201);
  expect((await upload.json()).asset).toEqual(document.assets[0]);
  const calls = mockRequests().length;
  await page.goto(`/preview/local/${RUN}/T2`);
  const other = await context.newPage();
  await other.goto(`/preview/local/${RUN}/T2`);
  await other.getByRole("tab", { name: "Edit" }).click();
  await page.getByRole("tab", { name: "Edit" }).click();

  const panel = page.getByRole("region", { name: "Teacher approval" });
  await expect(panel.getByText("AI: unresolved")).toBeVisible();
  await expect(panel.getByText("AI findings remain open")).toBeVisible();
  await panel.getByLabel("Reviewer name").fill("A. Teacher");
  await panel.getByLabel("Comment (optional)").fill("Reviewed for students");

  const block = page.getByRole("region", { name: "Block 1 (T2.1)", exact: true });
  const content = block.getByLabel("Content (Markdown and LaTeX)");
  await content.fill(`${await content.inputValue()} Draft only.`);
  await expect(panel.getByRole("button", { name: "Approve for students" })).toBeDisabled();
  await expect(panel.getByText("Save or discard your draft before making a decision.")).toBeVisible();
  await page.getByRole("region", { name: "Topic editor" }).getByRole("button", { name: "Discard draft" }).first().click();
  await page.getByRole("dialog", { name: "Discard your draft of T2?" }).getByRole("button", { name: "Discard" }).click();
  await expect(panel.getByRole("button", { name: "Approve for students" })).toBeEnabled();

  await panel.getByRole("button", { name: "Approve for students" }).dblclick();
  await expect(panel.getByText("Teacher approved", { exact: true })).toBeVisible();
  await expect(page.getByText("Text revision 1", { exact: true })).toBeVisible();
  const head = await request.get(notesUrl(RUN));
  const saved = await head.json();
  expect(saved.current_revision).toBe(1);
  expect(saved.document.sections[0].topics[1]).toMatchObject({ status: "unresolved", teacher_decision: { decision: "approved", reviewer: "A. Teacher" } });
  expect(mockRequests().length).toBe(calls);
  await expect.poll(async () => {
    const response = await request.get(notesUrl(RUN, `/render-jobs/${saved.render.id}`));
    return (await response.json()).status;
  }, { timeout: 120_000 }).toBe("done");
  const approvedHtml = await request.get(notesUrl(RUN, "/revisions/1/topics/T2/artifacts/html"));
  expect(approvedHtml.status()).toBe(200);
  expect(await approvedHtml.text()).not.toContain("Не повністю перевірено");

  const stale = await request.post(notesUrl(RUN, "/topics/T2/approval"), {
    data: { base_revision: 0, action: "revoke", reviewer: "Second teacher" },
  });
  expect(stale.status()).toBe(409);
  await other.bringToFront();
  await expect(other.getByText("Text revision 1", { exact: true })).toBeVisible();
  await expect(other.getByRole("region", { name: "Teacher approval" }).getByText("Teacher approved", { exact: true })).toBeVisible();

  await page.bringToFront();
  await page.getByRole("tab", { name: "History" }).click();
  await page.getByRole("button", { name: /Revision 1.*Teacher approved/ }).click();
  await expect(page.getByRole("region", { name: "Revision history" })).toContainText("Reviewed for students");
  await page.getByRole("tab", { name: "Edit" }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await panel.scrollIntoViewIfNeeded();
  await capture(page, testInfo, "mobile-390-teacher-approval");
  await capture(panel, testInfo, "mobile-390-teacher-approval-panel");
  await panel.getByLabel("Reviewer name").fill("A. Teacher");
  await panel.getByRole("button", { name: "Revoke approval" }).click();
  await expect(panel.getByText("Not teacher approved")).toBeVisible();
  await expect(page.getByText("Text revision 2", { exact: true })).toBeVisible();
  const after = await (await request.get(notesUrl(RUN))).json();
  await expect.poll(async () => {
    const response = await request.get(notesUrl(RUN, `/render-jobs/${after.render.id}`));
    return (await response.json()).status;
  }, { timeout: 120_000 }).toBe("done");
  const revokedHtml = await request.get(notesUrl(RUN, "/revisions/2/topics/T2/artifacts/html"));
  expect(revokedHtml.status()).toBe(200);
  expect(await revokedHtml.text()).toContain("Не повністю перевірено");
  expect(await (await request.get(notesUrl(RUN, "/revisions/1/topics/T2/artifacts/html"))).text()).not.toContain("Не повністю перевірено");
  await page.getByRole("tab", { name: "History" }).click();
  await capture(page, testInfo, "mobile-390-approval-history");
  await expect(page.getByRole("region", { name: "Revision history" })).toContainText("Teacher revoked approval");
  expect(mockRequests().length).toBe(calls);
});
