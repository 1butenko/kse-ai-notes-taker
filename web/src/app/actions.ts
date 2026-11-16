"use server";

import { signIn, signOut } from "@/auth";

export async function signInWithGoogle(formData: FormData) {
  const back = formData.get("callbackUrl");
  // Only paths of this app: never send the teacher to another site after sign-in.
  const redirectTo = typeof back === "string" && /^\/(?!\/)/.test(back) ? back : "/";
  await signIn("google", { redirectTo });
}

export async function signOutAction() {
  await signOut({ redirectTo: "/sign-in" });
}
