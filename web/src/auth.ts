import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

import { apiFetch } from "@/lib/api-token";

/**
 * Sign-in with Google, KSE Workspace accounts only. `hd` on the Google screen only narrows
 * the account picker; the check that counts is `signIn` below, on the verified ID token's
 * `hd` claim, which only accounts managed by that Workspace carry.
 */
const allowedDomains = (process.env.AUTH_ALLOWED_DOMAINS ?? "kse.org.ua")
  .split(",")
  .map((domain) => domain.trim().toLowerCase())
  .filter(Boolean);

type ApiUser = { id: string };

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Google({
      authorization: {
        params: {
          prompt: "select_account",
          // Google takes one domain here; more than one shows every account.
          ...(allowedDomains.length === 1 ? { hd: allowedDomains[0] } : {}),
        },
      },
    }),
  ],
  pages: { signIn: "/sign-in", error: "/sign-in" },
  session: { strategy: "jwt" },
  callbacks: {
    signIn({ account, profile }) {
      if (account?.provider !== "google" || !profile) return false;
      const domain = typeof profile.hd === "string" ? profile.hd.toLowerCase() : "";
      return profile.email_verified === true && allowedDomains.includes(domain);
    },
    async jwt({ token, account, profile }) {
      // First sign-in of this session: record the teacher and keep their id.
      if (account && profile?.sub && profile.email) {
        const user = await apiFetch<ApiUser>("web", "/auth/sync", {
          method: "POST",
          body: JSON.stringify({
            google_sub: profile.sub,
            email: profile.email,
            first_name: profile.given_name ?? "",
            last_name: profile.family_name ?? "",
            avatar_url: profile.picture ?? null,
          }),
        });
        token.uid = user.id;
      }
      return token;
    },
    session({ session, token }) {
      if (typeof token.uid === "string") session.user.id = token.uid;
      return session;
    },
  },
});
