import { defineConfig, devices } from "@playwright/test";

// Started by e2e/notes/stack.mjs (`npm run test:e2e:notes`), which owns the servers and
// the synthetic uploads root. Results live under that root and are kept on failure.
const root = process.env.NOTES_E2E_ROOT;
if (!root) {
  throw new Error("Run the notes E2E suite with `npm run test:e2e:notes`; it starts the test stack.");
}

export default defineConfig({
  testDir: "./e2e/notes",
  outputDir: `${root}/playwright/results`,
  workers: 1,
  fullyParallel: false,
  retries: 0,
  forbidOnly: !!process.env.CI,
  // Real Quarto renders the full notes and every topic in HTML and PDF.
  timeout: 10 * 60_000,
  expect: { timeout: 30_000 },
  reporter: [
    ["list"],
    ["html", { outputFolder: `${root}/playwright/report`, open: "never" }],
  ],
  use: {
    baseURL: process.env.NOTES_E2E_WEB_URL,
    actionTimeout: 30_000,
    navigationTimeout: 120_000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    // Traces already carry screencast frames; video also needs `npx playwright install ffmpeg`.
    video: process.env.NOTES_E2E_VIDEO === "1" ? "retain-on-failure" : "off",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // An installed Chrome instead of `npx playwright install chromium`.
        launchOptions: { executablePath: process.env.NOTES_E2E_CHROME || undefined },
      },
    },
  ],
});
