import fs from "node:fs";
import path from "node:path";

import { expect, test, type APIRequestContext } from "@playwright/test";

import {
  COURSE,
  LEGACY_RUN,
  attachDiagnostics,
  capture,
  control,
  mockRequests,
  notesUrl,
  stack,
  waitForRun,
  type RunView,
} from "./support";

// Real API -> worker -> Quarto; only the LLM answers come from the local mock.
test.describe.configure({ mode: "serial" });
test.afterEach(async ({}, testInfo) => attachDiagnostics(testInfo));

const topics = control.sections.flatMap((s) => s.topics);

// One generation per invocation, shared by the tests (and started by whichever runs first,
// so `-g` can select any of them).
let generation: Promise<RunView> | undefined;
function generated(request: APIRequestContext): Promise<RunView> {
  generation ??= (async () => {
    const started = await request.post(`${stack.api}/plans/${COURSE}/notes`);
    expect(started.status(), await started.text()).toBe(202);
    return waitForRun(request, (await started.json()).run.id, 8 * 60_000);
  })();
  return generation;
}

test("generation renders HTML and PDF through the worker and Quarto", async ({ request }) => {
  const run = await generated(request);

  const document = run.document!;
  expect(document.schema_version).toBe(2);
  expect(document.language).toBe("uk");
  expect(document.title).toBe(control.title);
  const notes = document.sections.flatMap((s) => s.topics);
  expect(notes.map((t) => [t.topic_id, t.status])).toEqual([
    ["T1", "verified"],
    ["T2", "unresolved"],
  ]);
  expect(notes[1].open_issues.length).toBeGreaterThan(0);
  expect(run.run.warnings.filter((w) => w.includes("not rendered"))).toEqual([]);

  // `done` can coexist with failed renders: every required artifact must be ready.
  const required = [null, ...topics.map((t) => t.topic_id)].flatMap((topic) =>
    ["html", "pdf"].map((format) => ({ topic, format })),
  );
  for (const { topic, format } of required) {
    const artifact = run.artifacts.find((a) => a.topic_id === topic && a.format === format);
    expect(artifact, `${format} of ${topic ?? "full notes"}`).toMatchObject({
      status: "ready",
      revision: 0,
    });
  }

  // The mock only stood in for the model: every pipeline stage asked it with its own model.
  const calls = mockRequests();
  expect(calls.filter((c) => c.error)).toEqual([]);
  expect(new Set(calls.map((c) => c.schema))).toEqual(
    new Set([
      "course_plan",
      "coverage_review",
      "evidence_selection",
      "topic_draft",
      "topic_verification",
      "consistency_edits",
    ]),
  );
  expect(calls.every((c) => c.model?.startsWith("e2e/"))).toBe(true);
  expect(calls.filter((c) => c.schema === "topic_verification" && c.topic === "T2").length)
    .toBeGreaterThan(1);
});

test("published artifacts are the real Quarto files", async ({ request }) => {
  const id = (await generated(request)).run.id;

  const html = await request.get(notesUrl(id, "/html"));
  expect(html.status()).toBe(200);
  expect(html.headers()["content-security-policy"]).toContain("sandbox allow-scripts");
  const page = await html.text();
  expect(page).toContain('lang="uk"');
  expect(page).toContain("MathJax");
  for (const id of ["eq-t1-augmented", "eq-t1-sarrus", "eq-t2-eigen", "tbl-t1-row-operations"]) {
    expect(page, id).toContain(`id="${id}"`);
  }
  expect(page).toContain("linear-systems.md"); // bibliography entry from the cited source

  for (const suffix of ["/pdf", "/topics/T1/pdf", "/topics/T2/pdf"]) {
    const pdf = await request.get(notesUrl(id, suffix));
    expect(pdf.status(), suffix).toBe(200);
    const body = await pdf.body();
    expect(body.subarray(0, 5).toString(), suffix).toBe("%PDF-");
    expect(body.length, suffix).toBeGreaterThan(10_000);
  }
  const topic = await request.get(notesUrl(id, "/topics/T2/html"));
  expect(topic.status()).toBe(200);
  // A standalone topic links other topics' content into the full HTML.
  expect(await topic.text()).toContain(`/plans/${COURSE}/notes/${id}/html#eq-t1-sarrus`);
});

test("the figure registers through the asset API", async ({ request }) => {
  const id = (await generated(request)).run.id;
  const png = fs.readFileSync(path.join(stack.fixtures, "figure.png"));

  const uploaded = await request.post(notesUrl(id, "/assets"), {
    multipart: { file: { name: "figure.png", mimeType: "image/png", buffer: png } },
  });

  expect(uploaded.status(), await uploaded.text()).toBe(201);
  const { asset, markdown_path } = await uploaded.json();
  expect(markdown_path).toBe(control.assets[0].path);
  const stored = await request.get(notesUrl(id, `/assets/${asset.id}`));
  expect(stored.status()).toBe(200);
  expect(stored.headers()["content-type"]).toBe("image/png");
  // Placing it into a saved revision through the editor: notes-workflow.spec.ts.
});

test("legacy notes still open without schema metadata", async ({ request, page }) => {
  const legacy = await request.get(notesUrl(LEGACY_RUN));
  expect(legacy.status()).toBe(200);
  const view = (await legacy.json()) as RunView;
  expect(view.document?.schema_version).toBe(1);
  expect(view.document?.language).toBe("uk");

  await page.goto(`/preview/${COURSE}/${LEGACY_RUN}`);
  await expect(page.getByRole("heading", { level: 1, name: control.title })).toBeVisible();
  await expect(page.getByText("The notes weren't rendered for this run.")).toBeVisible();
});

test("preview shows the notes with rendered math on desktop and 390 px", async ({ page, request }, testInfo) => {
  const id = (await generated(request)).run.id;
  await page.goto(`/preview/${COURSE}/${id}`);
  await expect(page.getByRole("heading", { level: 1, name: control.title })).toBeVisible();
  const frame = page.frameLocator(`iframe[title="${control.title}"]`);
  // MathJax loads from jsDelivr under the artifact CSP: offline runs fail here, by design.
  await expect(frame.locator("mjx-container").first()).toBeVisible({ timeout: 60_000 });
  await expect(frame.locator("#tbl-t1-row-operations")).toBeVisible();
  await expect(frame.getByText("?@")).toHaveCount(0);
  await capture(page, testInfo, "desktop-full-notes");

  const t2 = topics[1];
  await page.getByRole("navigation", { name: "Topics" }).getByRole("link", { name: new RegExp(t2.title) }).click();
  await expect(page).toHaveURL(new RegExp(`/preview/${COURSE}/${id}/${t2.topic_id}$`));
  await expect(page.getByRole("heading", { level: 1, name: t2.title })).toBeVisible();
  await expect(page.getByText("Unresolved").first()).toBeVisible();
  const topicFrame = page.frameLocator(`iframe[title="${t2.title}"]`);
  await expect(topicFrame.locator("mjx-container").first()).toBeVisible({ timeout: 60_000 });
  await capture(page, testInfo, "desktop-topic-T2");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/preview/${COURSE}/${id}`);
  await expect(frame.locator("mjx-container").first()).toBeVisible({ timeout: 60_000 });
  const pageOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(pageOverflow, "horizontal page scroll at 390 px").toBeLessThanOrEqual(0);
  const notesOverflow = await frame.locator("body").evaluate(
    (body) => body.scrollWidth - body.clientWidth,
  );
  expect(notesOverflow, "notes body wider than the 390 px frame").toBeLessThanOrEqual(0);
  await capture(page, testInfo, "mobile-390-full-notes");
  // Matrix, long formula and table at 390 px: Quarto's wrapper scrolls display math.
  for (const id of ["eq-t1-augmented", "eq-t1-sarrus", "tbl-t1-row-operations"]) {
    const element = frame.locator(`#${id}`);
    await element.scrollIntoViewIfNeeded();
    await capture(element, testInfo, `mobile-390-${id}`);
    // Wider content is acceptable only inside a container the reader can scroll.
    const clipped = await element.evaluate((start) => {
      for (let node: Element | null = start; node && node !== document.body; node = node.parentElement) {
        if (node.scrollWidth > node.clientWidth + 1) {
          const overflow = getComputedStyle(node).overflowX;
          return /auto|scroll/.test(overflow) ? null : `<${node.tagName.toLowerCase()} class="${node.className}"> overflow-x: ${overflow}`;
        }
      }
      return start.getBoundingClientRect().right > document.documentElement.clientWidth + 1
        ? "extends past the frame"
        : null;
    });
    expect(clipped, `${id} is clipped at 390 px`).toBeNull();
  }
});
