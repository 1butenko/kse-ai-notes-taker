import { connection } from "next/server";

import { API_URL } from "@/lib/api";

async function getApiStatus(): Promise<string> {
  try {
    const res = await fetch(`${API_URL}/health`, { cache: "no-store" });
    if (!res.ok) return `error (${res.status})`;
    const body: { status: string } = await res.json();
    return body.status;
  } catch {
    return "unreachable";
  }
}

export default async function Home() {
  await connection();
  const status = await getApiStatus();

  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-4 p-16 font-sans">
      <h1 className="text-3xl font-semibold tracking-tight">KSE AI Notes Taker</h1>
      <p className="text-zinc-600 dark:text-zinc-400">
        API status: <code className="font-mono">{status}</code>
      </p>
    </main>
  );
}
