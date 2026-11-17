# Security Policy

KSE AI Notes Taker is the dashboard KSE lecturers use to import their courses from Moodle (teaching.kse.org.ua), upload reading materials and turn them into AI-generated notes. It handles KSE Google accounts, course materials and the credentials of a Moodle bot account, so we take security reports seriously.

## Supported versions

Only the latest commit on `main` is supported. Production is deployed from `main`, so fixes land there and are not backported to older commits or branches.

| Version | Supported |
| ------- | --------- |
| `main` (latest) | Yes |
| Older commits, feature branches | No |

## Reporting a vulnerability

**Do not open a public issue, pull request or discussion for a security problem.**

Report it privately through GitHub:

1. Go to the [Security tab](https://github.com/1butenko/kse-ai-notes-taker/security) of this repository.
2. Click **Report a vulnerability**.
3. Fill in the form.

Please include:

- what the problem is and what an attacker could do with it;
- the affected part (`api/`, `api/app/worker`, `web/`, deployment) and the file or endpoint, if you know it;
- steps to reproduce, or a proof of concept;
- the commit you tested against.

### What to expect

| Step | Target time |
| ---- | ----------- |
| We confirm we got the report | 3 working days |
| We tell you whether we accept it and how severe it is | 7 working days |
| Fix for a critical or high-severity issue | 30 days |
| Fix for a medium or low-severity issue | 90 days |

We keep you updated while we work on it. Once the fix is deployed we publish a GitHub Security Advisory and credit you, unless you ask us not to.

## Scope

In scope, for example:

- **Authentication and access control:** signing in without a KSE account (Google sign-in, `AUTH_ALLOWED_DOMAINS`), forging or replaying the tokens the web and worker sign with `API_AUTH_SECRET`, or reading or changing another teacher's courses, materials or notes.
- **Secret exposure:** leaking the Moodle token, OpenRouter or Langfuse keys, AWS credentials or auth secrets through the API, the web app, logs, error messages or generated notes.
- **Imports and uploads:** server-side request forgery through URL imports, path traversal or unsafe file handling in uploads and S3 storage, and parsing of malicious PDF, DOCX or HTML files.
- **AI agents:** prompt injection in course materials that makes the agents call Moodle or other tools in ways the teacher did not ask for, or leak data from other courses.
- **Web app:** XSS, CSRF and similar issues in the dashboard and in rendered notes.
- **Injection:** SQL or command injection in the API or the worker.

Out of scope:

- Issues in Moodle, Google, OpenRouter, Langfuse or AWS themselves; report those to their owners.
- The shared sandbox course (`SHARED_COURSES`) being visible to every signed-in teacher; that is intended.
- Findings that need a stolen KSE account, physical access or a compromised device.
- Denial of service by flooding requests, spam and social engineering of KSE staff.
- Reports from automated scanners with no proof that the issue can be exploited.
- Missing best-practice headers or settings with no concrete impact.

## Rules for testing

- Test only against your own local copy (`make up`), not against the production deployment.
- Do not access, change or delete data that is not yours, and do not use real KSE student or teacher data.
- Do not use a real Moodle token against teaching.kse.org.ua beyond what the app already does.
- Give us reasonable time to fix the issue before you disclose it publicly.

If you follow these rules in good faith, we will not take action against you over your research.

## For contributors

- Never commit `.env` or any secret. Use `.env.example` for new settings, with empty values.
- Production secrets live in AWS SSM Parameter Store, not in the repository.
- If you commit a secret by mistake, tell the maintainers straight away and rotate it; removing it from git history is not enough.
- Course materials are sent to OpenRouter and, when `LANGFUSE_TRACING` is on, to Langfuse. Keep that in mind before adding new data to prompts or traces.
