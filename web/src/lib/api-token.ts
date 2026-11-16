import { createHmac } from "node:crypto";

/**
 * Server-side calls to the FastAPI app carry a short-lived HS256 token signed with
 * API_AUTH_SECRET (see api/app/auth.py): `sub` is the signed-in teacher's id, or "web" for the
 * web's own calls (recording a sign-in). Never import this into client code.
 */

export const API_URL = process.env.API_URL ?? "http://localhost:8000";

const TOKEN_SECONDS = 60;

function b64url(data: string | Buffer): string {
  return Buffer.from(data).toString("base64url");
}

export function apiToken(subject: string): string {
  const secret = process.env.API_AUTH_SECRET;
  if (!secret) throw new Error("API_AUTH_SECRET is not set; see .env.example");
  const now = Math.floor(Date.now() / 1000);
  const header = b64url(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const payload = b64url(
    JSON.stringify({ iss: "kse-web", aud: "kse-api", sub: subject, iat: now, exp: now + TOKEN_SECONDS }),
  );
  const signature = createHmac("sha256", secret).update(`${header}.${payload}`).digest();
  return `${header}.${payload}.${b64url(signature)}`;
}

/** A JSON call to the API as `subject`, from the server. */
export async function apiFetch<T>(subject: string, path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      ...init?.headers,
      "content-type": "application/json",
      authorization: `Bearer ${apiToken(subject)}`,
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `API ${res.status}`);
  }
  return res.json();
}
