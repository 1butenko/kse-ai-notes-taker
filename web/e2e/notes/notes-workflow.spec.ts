import { test } from "@playwright/test";

// Task 12 (P3.3) scenarios that need interfaces which have not landed yet. They are
// reported as `fixme` (skipped), never as passing. Replace each body when its
// dependencies land; see e2e/notes/README.md for the step-by-step expectations.

const dependsOn = (...tasks: string[]) =>
  tasks.map((description) => ({ type: "depends-on", description }));

test.fixme(
  "HTML → edit → save → new revision → artifacts ready → history → restore",
  {
    annotation: dependsOn(
      "Task 6 / P2.1: revisions API (GET .../revisions, PATCH .../topics/{topic}, POST .../restore)",
      "Task 7 / P2.2: block editor, diff and restore UI",
      "Task 8 / P2.3: revision render jobs and revision artifact routes",
    ),
  },
  async () => {},
);

test.fixme(
  "AI suggestion: reject keeps the revision, apply creates a verified-stale revision",
  {
    annotation: dependsOn(
      "Task 9 / P2.4: POST .../suggestions, GET .../suggestions/{id}, apply/reject",
      "Mock OpenRouter: answers for the suggestion and re-verification schemas once named",
    ),
  },
  async () => {},
);

test.fixme(
  "Word download and course book search from one revision",
  {
    annotation: dependsOn(
      "Task 10 / P3.1: DOCX revision artifacts and download",
      "Task 11 / P3.2: book render job, GET .../revisions/{revision}/book/{asset_path}",
    ),
  },
  async () => {},
);
