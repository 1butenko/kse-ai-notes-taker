import {
  approveAllProposals,
  approveProposal,
  mapMaterials,
  type PlanView,
  type SessionView,
} from "@/lib/api";

/**
 * Maps the readings to the lectures and approves what it found, with no review step:
 * exact excerpts (citation pages, bookmarks) and AI-estimated ones alike. The estimated
 * ones stay visible on their lecture as "Check pages"; mapping never overwrites a
 * proposal the lecturer already approved, rejected or edited.
 */
export async function autoMatch(course: string): Promise<PlanView> {
  await mapMaterials(course);
  let plan = await approveAllProposals(course);
  const estimated = plan.sessions
    .flatMap((s) => s.proposals)
    .filter((p) => p.status === "proposed" && p.method === "toc");
  for (const p of estimated) {
    if (p.pdf_start === null || p.pdf_end === null) continue;
    plan = await approveProposal(course, p.id, { pdf_start: p.pdf_start, pdf_end: p.pdf_end });
  }
  return plan;
}

/** Approved excerpts whose pages an LLM estimated from the table of contents. */
export function estimatedExcerpts(entry: SessionView) {
  return entry.proposals.filter((p) => p.status === "approved" && p.method === "toc");
}

/** Citations whose pages the mapping could not find in any book. */
export function missingPages(entry: SessionView) {
  return entry.proposals.filter(
    (p) => p.status === "proposed" && (p.pdf_start === null || p.pdf_end === null),
  );
}
