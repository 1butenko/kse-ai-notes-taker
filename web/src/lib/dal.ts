import "server-only";

import { cache } from "react";
import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { apiFetch } from "@/lib/api-token";

export type Me = {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  avatar_url: string | null;
};

/** The signed-in teacher's session, or a redirect to the sign-in page. */
export const verifySession = cache(async () => {
  const session = await auth();
  if (!session?.user?.id) redirect("/sign-in");
  return { userId: session.user.id, user: session.user };
});

/** The teacher's account (names as they edited them), or null when the API is unreachable. */
export const getMe = cache(async (): Promise<Me | null> => {
  const { userId } = await verifySession();
  try {
    return await apiFetch<Me>(userId, "/me");
  } catch {
    return null;
  }
});
