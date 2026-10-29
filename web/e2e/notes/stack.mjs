#!/usr/bin/env node
// Isolated notes E2E stack: mock OpenRouter -> worker -> API -> web, then Playwright.
//
//   npm run test:e2e:notes [-- <playwright args>]   run the browser suite
//   npm run test:e2e:notes -- --hold                 start the stack for manual QA, Ctrl+C stops
//
// Every invocation gets a fresh synthetic uploads root; no .env, production uploads or keys
// are passed to the servers. The root (logs, mock log, traces, screenshots) is kept on
// failure, or always with NOTES_E2E_KEEP=1. Only the process groups started here are stopped.

import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const API = path.resolve(WEB, "../api");
const HOST = "127.0.0.1";
const PORTS = {
  mock: Number(process.env.NOTES_E2E_MOCK_PORT ?? 8126),
  worker: Number(process.env.NOTES_E2E_WORKER_PORT ?? 8125),
  api: Number(process.env.NOTES_E2E_API_PORT ?? 8124),
  web: Number(process.env.NOTES_E2E_WEB_PORT ?? 3124),
};
const PYTHON = process.env.NOTES_E2E_PYTHON ?? path.join(API, ".venv/bin/python");
const QUARTO = process.env.NOTES_E2E_QUARTO_BIN ?? process.env.QUARTO_BIN ?? "quarto";
const TMP = process.env.NOTES_E2E_TMPDIR ?? (process.platform === "darwin" ? "/private/tmp" : os.tmpdir());

const args = process.argv.slice(2);
const hold = args.includes("--hold");
const playwrightArgs = args.filter((a) => a !== "--hold");

const url = (port) => `http://${HOST}:${port}`;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const started = [];
let root;

function fail(message) {
  throw new Error(message);
}

function preflight() {
  if (!fs.existsSync(PYTHON)) {
    fail(`API Python not found at ${PYTHON}. Run \`cd api && uv sync\` or set NOTES_E2E_PYTHON.`);
  }
  const quarto = spawnSync(QUARTO, ["--version"], { encoding: "utf8" });
  if (quarto.status !== 0) {
    fail(`Quarto is required (real renders are part of the test): \`${QUARTO} --version\` failed. ` +
      "Install Quarto or set NOTES_E2E_QUARTO_BIN.");
  }
  return quarto.stdout.trim();
}

function portFree(port) {
  return new Promise((resolve) => {
    const socket = net.connect({ host: HOST, port });
    socket.once("connect", () => {
      socket.destroy();
      resolve(false);
    });
    socket.once("error", () => resolve(true));
  });
}

// Only what the tools need to run: HOME/PATH for uv, Node, Quarto and Typst caches.
function baseEnv() {
  const env = {};
  for (const key of ["PATH", "HOME", "USER", "LANG", "LC_ALL", "TMPDIR", "TYPST_FONT_PATHS"]) {
    if (process.env[key]) env[key] = process.env[key];
  }
  return env;
}

function pythonEnv(uploads) {
  return {
    ...baseEnv(),
    PYTHONUNBUFFERED: "1",
    PYTHONDONTWRITEBYTECODE: "1",
    ENVIRONMENT: "notes-e2e",
    UPLOADS_DIR: uploads,
    PUBLIC_API_URL: url(PORTS.api),
    MOODLE_URL: `${url(PORTS.mock)}/unused-moodle`,
    MOODLE_TOKEN: "e2e-unused",
    WORKER_URL: url(PORTS.worker),
    CORS_ORIGINS: JSON.stringify([url(PORTS.web)]),
    CORS_ORIGIN_REGEX: `^http://127[.]0[.]0[.]1:${PORTS.web}$`,
    OPENROUTER_URL: `${url(PORTS.mock)}/api/v1`,
    OPENROUTER_API_KEY: "e2e-local-only",
    OPENROUTER_MODEL: "e2e/default",
    NOTES_PLANNER_MODEL: "e2e/planner",
    NOTES_SELECTOR_MODEL: "e2e/selector",
    NOTES_WRITER_MODEL: "e2e/writer",
    NOTES_VERIFIER_MODEL: "e2e/verifier",
    NOTES_ESCALATION_MODEL: "e2e/escalation",
    NOTES_CONCURRENCY: "1",
    QUARTO_CONCURRENCY: "1",
    QUARTO_BIN: path.join(root, "quarto"),
    NOTES_E2E_MOCK_LOG: path.join(root, "logs", "openrouter.jsonl"),
  };
}

function start(name, command, commandArgs, options) {
  const log = fs.openSync(path.join(root, "logs", `${name}.log`), "a");
  const child = spawn(command, commandArgs, {
    ...options,
    detached: true, // own process group: stopping it also stops Next/Quarto children
    stdio: ["ignore", log, log],
  });
  const entry = { name, child, exited: null };
  child.once("exit", (code, signal) => (entry.exited = { code, signal }));
  started.push(entry);
  return entry;
}

async function ready(entry, target, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (entry.exited) fail(`${entry.name} exited before it was ready (${JSON.stringify(entry.exited)})`);
    try {
      const response = await fetch(target, { signal: AbortSignal.timeout(5_000) });
      if (response.status < 500) return;
    } catch {
      // not listening yet
    }
    await sleep(500);
  }
  fail(`${entry.name} was not ready at ${target} within ${timeoutMs / 1000}s`);
}

async function stop() {
  for (const entry of [...started].reverse()) {
    if (entry.exited) continue;
    try {
      process.kill(-entry.child.pid, "SIGTERM");
    } catch {
      continue;
    }
    const deadline = Date.now() + 10_000;
    while (!entry.exited && Date.now() < deadline) await sleep(100);
    if (!entry.exited) {
      try {
        process.kill(-entry.child.pid, "SIGKILL");
      } catch {
        // already gone
      }
    }
  }
  started.length = 0;
}

function tails() {
  for (const name of ["mock", "worker", "api", "web"]) {
    const file = path.join(root, "logs", `${name}.log`);
    if (!fs.existsSync(file)) continue;
    const lines = fs.readFileSync(file, "utf8").trimEnd().split("\n").slice(-25);
    console.error(`\n--- ${name}.log (last ${lines.length} lines) ---\n${lines.join("\n")}`);
  }
}

async function main() {
  const quartoVersion = preflight();
  for (const [name, port] of Object.entries(PORTS)) {
    if (!(await portFree(port))) {
      fail(`Port ${port} (${name}) is already in use; refusing to reuse an unknown service. ` +
        `Stop it or set NOTES_E2E_${name.toUpperCase()}_PORT.`);
    }
  }

  root = fs.mkdtempSync(path.join(TMP, "kse-notes-e2e-"));
  const uploads = path.join(root, "uploads");
  fs.mkdirSync(path.join(root, "logs"), { recursive: true });
  fs.mkdirSync(uploads);
  console.log(`notes-e2e: root ${root} (Quarto ${quartoVersion})`);
  // A per-stack launcher lets acceptance tests make Quarto unavailable without
  // modifying the installed tool or restarting the serving worker.
  const launcher = path.join(root, "quarto");
  fs.writeFileSync(launcher, `#!${PYTHON}\nimport os, pathlib, sys\nif pathlib.Path(${JSON.stringify(path.join(root, "quarto-disabled"))}).exists():\n    sys.exit("Quarto disabled for acceptance test")\nos.execvp(${JSON.stringify(QUARTO)}, [${JSON.stringify(QUARTO)}, *sys.argv[1:]])\n`);
  fs.chmodSync(launcher, 0o755);

  const env = pythonEnv(uploads);
  const seeded = spawnSync(PYTHON, ["-m", "tests.e2e.synthetic", "seed", uploads], {
    cwd: API,
    env,
    encoding: "utf8",
  });
  if (seeded.status !== 0) fail(`Seeding failed:\n${seeded.stdout}${seeded.stderr}`);

  const uvicorn = (app, port) => ["-m", "uvicorn", app, "--host", HOST, "--port", String(port)];
  const mock = start("mock", PYTHON, uvicorn("tests.e2e.mock_openrouter:app", PORTS.mock), { cwd: API, env });
  await ready(mock, `${url(PORTS.mock)}/health`, 60_000);
  const worker = start("worker", PYTHON, uvicorn("app.worker.main:app", PORTS.worker), { cwd: API, env });
  await ready(worker, `${url(PORTS.worker)}/health`, 60_000);
  const api = start("api", PYTHON, uvicorn("app.main:app", PORTS.api), { cwd: API, env });
  await ready(api, `${url(PORTS.api)}/health`, 60_000);
  const web = start(
    "web",
    "npm",
    ["run", "dev", "--", "--webpack", "--hostname", HOST, "--port", String(PORTS.web)],
    {
      cwd: WEB,
      env: {
        ...baseEnv(),
        NEXT_TELEMETRY_DISABLED: "1",
        API_URL: url(PORTS.api),
        API_PORT: String(PORTS.api),
        NEXT_PUBLIC_API_URL: url(PORTS.api),
      },
    },
  );
  await ready(web, url(PORTS.web), 240_000);
  console.log(`notes-e2e: stack ready, web ${url(PORTS.web)}, API ${url(PORTS.api)}`);

  if (hold) {
    console.log("notes-e2e: holding the stack for manual QA; press Ctrl+C to stop");
    await new Promise(() => {});
  }

  const playwright = spawn("npx", ["playwright", "test", "--config", "playwright.notes.config.ts", ...playwrightArgs], {
    cwd: WEB,
    stdio: "inherit",
    env: {
      ...process.env,
      NOTES_E2E_ROOT: root,
      NOTES_E2E_UPLOADS: uploads,
      NOTES_E2E_LOGS: path.join(root, "logs"),
      NOTES_E2E_API_URL: url(PORTS.api),
      NOTES_E2E_WEB_URL: url(PORTS.web),
      NOTES_E2E_FIXTURES: path.join(API, "tests/fixtures/notes"),
    },
  });
  return await new Promise((resolve) => playwright.once("exit", (code) => resolve(code ?? 1)));
}

let exiting = false;
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, async () => {
    if (exiting) return;
    exiting = true;
    await stop();
    if (root) console.error(`notes-e2e: interrupted; kept ${root}`);
    process.exit(130);
  });
}

let code = 1;
try {
  code = await main();
} catch (error) {
  console.error(`notes-e2e: ${error.message}`);
  if (root) tails();
} finally {
  await stop();
}
if (root && (code !== 0 || process.env.NOTES_E2E_KEEP === "1")) {
  console.error(`notes-e2e: kept ${root} (logs/, playwright/report, traces and screenshots)`);
} else if (root) {
  fs.rmSync(root, { recursive: true, force: true });
}
process.exit(code);
