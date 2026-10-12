let session: string | null = null;

export function tabSession(): string {
  if (typeof window === "undefined") return "";
  session ??= crypto.randomUUID();
  return session;
}
