"use client";

import { useState } from "react";
import { BookOpenIcon, CheckIcon, EyeIcon, RotateCcwIcon, XIcon } from "lucide-react";

import { useFileViewer } from "@/components/dashboard/file-viewer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import {
  approveProposal,
  fileName,
  rejectProposal,
  reopenProposal,
  setBook,
  type PlanView,
  type Proposal,
  type ProposalMethod,
  type SavedFile,
} from "@/lib/api";

export type Update = (action: () => Promise<PlanView>) => void;

const METHOD_LABELS: Record<ProposalMethod, string> = {
  pages: "from citation pages",
  bookmarks: "from bookmarks",
  toc: "AI-estimated",
  manual: "entered by you",
};

export const EXACT_METHODS: ProposalMethod[] = ["pages", "bookmarks"];

export function MethodBadge({ method }: { method: ProposalMethod }) {
  const exact = EXACT_METHODS.includes(method);
  return <Badge variant={exact ? "secondary" : "outline"}>{METHOD_LABELS[method]}</Badge>;
}

function pagesText(p: {
  pdf_start: number | null;
  pdf_end: number | null;
  printed: string | null;
}) {
  if (p.pdf_start === null || p.pdf_end === null) return "pages not found";
  const pdf =
    p.pdf_start === p.pdf_end ? `PDF p. ${p.pdf_start}` : `PDF pp. ${p.pdf_start}–${p.pdf_end}`;
  return p.printed ? `${p.printed} (${pdf})` : pdf;
}

function ProposalRow({
  proposal,
  course,
  update,
}: {
  proposal: Proposal;
  course: string;
  update: Update;
}) {
  const openFile = useFileViewer();
  const [start, setStart] = useState(proposal.pdf_start?.toString() ?? "");
  const [end, setEnd] = useState(proposal.pdf_end?.toString() ?? "");
  const pages = { pdf_start: Number(start), pdf_end: Number(end) };
  const notFound = proposal.pdf_start === null || proposal.pdf_end === null;
  const valid =
    Number.isInteger(pages.pdf_start) &&
    Number.isInteger(pages.pdf_end) &&
    pages.pdf_start >= 1 &&
    pages.pdf_start <= pages.pdf_end;

  return (
    <li
      className={cn(
        "flex flex-col gap-2 rounded-md border border-dashed p-2 text-sm",
        notFound && "border-destructive/50 bg-destructive/5",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{proposal.label}</span>
        <span className={notFound ? "text-destructive" : "text-muted-foreground"}>
          {fileName(proposal.book)} · {pagesText(proposal)}
        </span>
        <MethodBadge method={proposal.method} />
      </div>
      {proposal.note && <p className="text-xs text-muted-foreground">{proposal.note}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground">PDF pages</span>
        <Input
          aria-label="First PDF page"
          inputMode="numeric"
          className="h-8 w-20"
          value={start}
          onChange={(event) => setStart(event.target.value)}
        />
        <span>to</span>
        <Input
          aria-label="Last PDF page"
          inputMode="numeric"
          className="h-8 w-20"
          value={end}
          onChange={(event) => setEnd(event.target.value)}
        />
        <Button
          variant="ghost"
          size="sm"
          disabled={!valid}
          onClick={() =>
            openFile({ path: proposal.book, page: pages.pdf_start, title: proposal.label })
          }
        >
          <EyeIcon />
          Open
        </Button>
        <Button
          size="sm"
          disabled={!valid}
          onClick={() => update(() => approveProposal(course, proposal.id, pages))}
        >
          <CheckIcon />
          Approve
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => update(() => rejectProposal(course, proposal.id))}
        >
          <XIcon />
          Reject
        </Button>
      </div>
    </li>
  );
}

/** Open proposals of one session, with its rejected ones folded away. */
export function SessionProposals({
  proposals,
  course,
  update,
}: {
  proposals: Proposal[];
  course: string;
  update: Update;
}) {
  const open = proposals.filter((p) => p.status === "proposed");
  const rejected = proposals.filter((p) => p.status === "rejected");
  if (open.length === 0 && rejected.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      {open.length > 0 && (
        <>
          <span className="text-xs font-medium text-muted-foreground">
            Proposed excerpts
          </span>
          <ul className="flex flex-col gap-2">
            {open.map((proposal) => (
              <ProposalRow
                // Reset the page inputs when a re-run replaces the proposal.
                key={`${proposal.id}-${proposal.pdf_start}-${proposal.pdf_end}`}
                proposal={proposal}
                course={course}
                update={update}
              />
            ))}
          </ul>
        </>
      )}
      {rejected.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-xs text-muted-foreground">
            Rejected ({rejected.length})
          </summary>
          <ul className="mt-1 flex flex-col gap-1">
            {rejected.map((proposal) => (
              <li key={proposal.id} className="flex items-center gap-2 text-muted-foreground">
                <span className="line-through">
                  {proposal.label} · {pagesText(proposal)}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => update(() => reopenProposal(course, proposal.id))}
                >
                  <RotateCcwIcon />
                  Undo
                </Button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/** Which uploaded PDF holds each course material, plus the books nobody uploaded. */
export function BooksPanel({
  plan,
  readingFiles,
  update,
}: {
  plan: PlanView;
  readingFiles: SavedFile[];
  update: Update;
}) {
  const pdfs = readingFiles.filter((file) => /\.pdf$/i.test(file.path));
  const citedBy = new Map<number, number>();
  for (const entry of plan.sessions) {
    const refs = new Set(
      [...entry.session.required_readings, ...entry.session.optional_readings]
        .map((r) => r.material_ref)
        .filter((ref) => ref !== null),
    );
    for (const ref of refs) citedBy.set(ref, (citedBy.get(ref) ?? 0) + 1);
  }
  const missing = plan.books.filter((book) => !book.file && citedBy.has(book.material));

  return (
    <div className="flex flex-col gap-3 rounded-lg border p-3">
      <div className="flex items-center gap-2 font-medium">
        <BookOpenIcon className="size-4" />
        Books
      </div>
      <ul className="flex flex-col gap-2 text-sm">
        {plan.books.map((book) => (
          <li
            key={book.material}
            className="flex flex-col gap-1 sm:flex-row sm:items-center sm:gap-3"
          >
            <span className="min-w-0 flex-1">{book.raw}</span>
            <select
              aria-label={`File for ${book.raw}`}
              className="h-8 rounded-md border bg-background px-2 text-sm sm:w-72"
              value={book.file ?? ""}
              onChange={(event) =>
                update(() => setBook(plan.course, book.material, event.target.value || null))
              }
            >
              <option value="">Not uploaded</option>
              {pdfs.map((file) => (
                <option key={file.path} value={file.path}>
                  {fileName(file.path)}
                </option>
              ))}
            </select>
            {book.confirmed && <Badge variant="outline">set by you</Badge>}
          </li>
        ))}
      </ul>
      {missing.length > 0 && (
        <div className="flex flex-col gap-1 border-t pt-2 text-sm">
          <span className="font-medium">Not uploaded</span>
          {missing.map((book) => {
            const n = citedBy.get(book.material) ?? 0;
            return (
              <span key={book.material} className="text-muted-foreground">
                {book.raw}: {n} {n === 1 ? "session cites" : "sessions cite"} it. Upload it to the
                reading materials and press Map materials again.
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}
