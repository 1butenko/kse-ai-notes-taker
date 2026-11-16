import type { NextRequest } from "next/server";

import { auth } from "@/auth";
import { API_URL, apiToken } from "@/lib/api-token";

/**
 * The browser's door to the API: every `/api/*` call (except Auth.js's own `/api/auth/*`)
 * is forwarded to FastAPI as the signed-in teacher, with a short-lived token. Bodies and
 * responses are streamed, so uploads and file downloads pass through unchanged.
 */

// Request headers that belong to this hop, or that the API must not get from the browser.
const DROP_REQUEST = ["host", "cookie", "authorization", "connection", "content-length", "accept-encoding"];
// fetch() already decoded the body, so its length and encoding no longer hold.
const DROP_RESPONSE = ["content-encoding", "content-length", "transfer-encoding", "connection"];

async function forward(request: NextRequest, ctx: RouteContext<"/api/[...path]">) {
  const session = await auth();
  if (!session?.user?.id) {
    return Response.json({ detail: "Sign in first" }, { status: 401 });
  }
  const { path } = await ctx.params;
  const url = new URL(`${API_URL}/${path.map(encodeURIComponent).join("/")}`);
  url.search = request.nextUrl.search;

  const headers = new Headers(request.headers);
  for (const name of DROP_REQUEST) headers.delete(name);
  headers.set("authorization", `Bearer ${apiToken(session.user.id)}`);

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  let upstream: Response;
  try {
    upstream = await fetch(url, {
      method: request.method,
      headers,
      body: hasBody ? request.body : undefined,
      // Stream the request body (uploads) instead of buffering it.
      ...(hasBody ? { duplex: "half" } : {}),
      redirect: "manual",
      cache: "no-store",
      signal: request.signal,
    } as RequestInit);
  } catch {
    return Response.json({ detail: "The API is unreachable" }, { status: 502 });
  }

  const out = new Headers(upstream.headers);
  for (const name of DROP_RESPONSE) out.delete(name);
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export { forward as DELETE, forward as GET, forward as PATCH, forward as POST, forward as PUT };
