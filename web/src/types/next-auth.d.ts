import "next-auth/jwt";

declare module "next-auth/jwt" {
  interface JWT {
    /** The teacher's id in the API's `users` table. */
    uid?: string;
  }
}
