import { NextResponse } from "next/server";

import { auth } from "@/auth";

/**
 * Optimistic check: pages need a session, so a signed-out visitor goes to the sign-in page.
 * The real checks are in the pages (src/lib/dal.ts) and in the `/api` route handler, which
 * this skips: Proxy buffers request bodies, which would cap uploads.
 */
export default auth((request) => {
  if (request.auth) return;
  const signIn = new URL("/sign-in", request.nextUrl.origin);
  const back = request.nextUrl.pathname + request.nextUrl.search;
  if (back !== "/") signIn.searchParams.set("callbackUrl", back);
  return NextResponse.redirect(signIn);
});

export const config = {
  matcher: ["/((?!api|sign-in|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|webp|ico|woff2?)$).*)"],
};
