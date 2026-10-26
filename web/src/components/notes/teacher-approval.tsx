"use client";

import { useRef, useState } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { ApiError, decideNotesTopic, type TopicNote } from "@/lib/api";

type Props = {
  course: string;
  run: string;
  revision: number;
  topic: TopicNote;
  hasDraft: boolean;
  refresh: () => Promise<unknown>;
};

export function TeacherApproval({ course, run, revision, topic, hasDraft, refresh }: Props) {
  const [reviewer, setReviewer] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);
  const approved = topic.teacher_decision?.decision === "approved";
  const eligible = (topic.status === "verified" || topic.status === "unresolved") &&
    topic.blocks.some((block) => block.content.trim());

  const submit = async (action: "approve" | "revoke") => {
    if (inFlight.current || hasDraft || !reviewer.trim()) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await decideNotesTopic(course, run, topic.topic_id, {
        base_revision: revision,
        action,
        reviewer: reviewer.trim(),
        comment: comment.trim() || null,
      });
      await refresh();
      setComment("");
      toast.success(`${action === "approve" ? "Approved" : "Revoked approval"} in revision ${result.revision.revision}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        await refresh();
        setError("The notes changed in another tab. Review the current text before deciding again.");
      } else {
        setError(err instanceof ApiError ? err.message : "Couldn't reach the server. Please try again.");
      }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  return (
    <section aria-label="Teacher approval" className="space-y-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-medium">Teacher approval for students</h3>
        {approved ? <Badge>Teacher approved</Badge> : <Badge variant="outline">Not teacher approved</Badge>}
        <Badge variant="outline">AI: {topic.status}{topic.verification_stale ? " (outdated)" : ""}</Badge>
      </div>
      <p className="text-sm text-muted-foreground">
        Approval removes the automatic AI caution from student downloads for this saved text. It does not change the AI check or findings. The reviewer name is self-declared.
      </p>
      {topic.open_issues.length > 0 && (
        <Alert>
          <AlertTitle>AI findings remain open</AlertTitle>
          <AlertDescription>
            <ul className="list-disc space-y-1 pl-5">
              {topic.open_issues.map((issue, index) => <li key={index}>{issue.detail}</li>)}
            </ul>
          </AlertDescription>
        </Alert>
      )}
      {approved && topic.teacher_decision && (
        <p className="text-xs text-muted-foreground">
          Approved by {topic.teacher_decision.reviewer} on {new Date(topic.teacher_decision.at).toLocaleString()}.
        </p>
      )}
      {hasDraft && <p className="text-sm text-warning">Save or discard your draft before making a decision.</p>}
      {!eligible && <p className="text-sm text-muted-foreground">Only saved topics with content can be approved.</p>}
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1"><Label htmlFor="approval-reviewer">Reviewer name</Label>
          <Input id="approval-reviewer" value={reviewer} maxLength={120} onChange={(e) => setReviewer(e.target.value)} placeholder="Your name" />
        </div>
        <div className="space-y-1"><Label htmlFor="approval-comment">Comment (optional)</Label>
          <Input id="approval-comment" value={comment} maxLength={2000} onChange={(e) => setComment(e.target.value)} />
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button disabled={busy || hasDraft || !eligible || approved || !reviewer.trim()} onClick={() => submit("approve")}>
          {busy && <Spinner />} Approve for students
        </Button>
        <Button variant="outline" disabled={busy || hasDraft || !approved || !reviewer.trim()} onClick={() => submit("revoke")}>
          Revoke approval
        </Button>
      </div>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </section>
  );
}
