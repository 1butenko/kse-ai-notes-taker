"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import "katex/dist/katex.min.css";

import { Skeleton } from "@/components/ui/skeleton";

/** What was loaded, and for which URL: a stale result reads as still loading. */
type Loaded = { url: string; text: string | null };

/** A Markdown reading (a saved web page) rendered with tables, math and images. */
export function MarkdownPreview({ url }: { url: string }) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);

  useEffect(() => {
    let current = true;
    fetch(url)
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status));
        return response.text();
      })
      .then(
        (text) => current && setLoaded({ url, text }),
        () => current && setLoaded({ url, text: null }),
      );
    return () => {
      current = false;
    };
  }, [url]);

  const state =
    loaded?.url !== url
      ? { status: "loading" as const }
      : loaded.text === null
        ? { status: "failed" as const }
        : { status: "ready" as const, text: loaded.text };

  if (state.status === "loading") {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
      </div>
    );
  }
  if (state.status === "failed") {
    return <p className="text-muted-foreground">Couldn&apos;t load this reading.</p>;
  }
  return (
    <div className="markdown-preview min-h-0 flex-1 overflow-y-auto rounded-lg border px-6 py-5">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          a: (props) => <a {...props} target="_blank" rel="noreferrer" />,
          // eslint-disable-next-line @next/next/no-img-element -- external images of any size
          img: ({ alt, ...props }) => <img alt={alt ?? ""} loading="lazy" {...props} />,
        }}
      >
        {state.text}
      </ReactMarkdown>
    </div>
  );
}
