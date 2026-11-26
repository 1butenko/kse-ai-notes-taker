"use client";

/** A live preview of a Graphviz or Mermaid cell. Both libraries load only when a preview is
 * shown. The SVG is drawn in an <img>, so nothing in a diagram (links, scripts) runs in the
 * app; the published page draws it again, in its sandbox. */

import { useEffect, useState } from "react";
import { CircleAlertIcon } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Spinner } from "@/components/ui/spinner";

type Kind = "dot" | "mermaid";

let mermaidReady: Promise<typeof import("mermaid").default> | null = null;
function loadMermaid() {
  mermaidReady ??= import("mermaid").then(({ default: mermaid }) => {
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      // Plain SVG text: an <img> doesn't draw HTML labels.
      htmlLabels: false,
      flowchart: { htmlLabels: false },
      theme: "neutral",
    });
    return mermaid;
  });
  return mermaidReady;
}

let vizReady: Promise<{ renderString: (dot: string, options: { format: "svg" }) => string }> | null =
  null;
function loadViz() {
  vizReady ??= import("@viz-js/viz").then(({ instance }) => instance());
  return vizReady;
}

let count = 0;

async function render(kind: Kind, code: string): Promise<string> {
  if (kind === "dot") return (await loadViz()).renderString(code, { format: "svg" });
  const mermaid = await loadMermaid();
  const { svg } = await mermaid.render(`mermaid-preview-${++count}`, code);
  return svg;
}

export function DiagramPreview({ kind, code }: { kind: Kind; code: string }) {
  const [state, setState] = useState<{ src?: string; error?: string; code?: string }>({});

  useEffect(() => {
    let current = true;
    const timer = setTimeout(() => {
      render(kind, code).then(
        (svg) =>
          current &&
          setState({
            code,
            src: `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`,
          }),
        (error: unknown) =>
          current &&
          setState({ code, error: error instanceof Error ? error.message : String(error) }),
      );
    }, 400);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [kind, code]);

  if (state.error) {
    return (
      <Alert variant="destructive">
        <CircleAlertIcon />
        <AlertDescription className="font-mono text-xs whitespace-pre-wrap">
          {state.error.split("\n").slice(0, 6).join("\n")}
        </AlertDescription>
      </Alert>
    );
  }
  if (!state.src) {
    return (
      <div className="flex h-24 items-center justify-center">
        <Spinner className="text-muted-foreground" />
      </div>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element -- a generated SVG, drawn inert
    <img
      src={state.src}
      alt="Diagram preview"
      className="mx-auto max-h-96 max-w-full"
    />
  );
}
