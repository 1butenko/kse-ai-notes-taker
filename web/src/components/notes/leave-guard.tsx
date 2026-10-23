"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/**
 * Asks before leaving a page with an unsaved draft: browser unload, guarded links and
 * programmatic topic changes. Leaving keeps the draft in this tab's sessionStorage.
 */
export function useLeaveGuard(active: boolean) {
  const router = useRouter();
  const [target, setTarget] = useState<string | null>(null);

  useEffect(() => {
    if (!active) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      // Older browsers show the prompt only when returnValue is set.
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [active]);

  return {
    /** For `<Link onNavigate>`: stops a client-side navigation and asks first. */
    onNavigate: (href: string) => (event: { preventDefault: () => void }) => {
      if (!active) return;
      event.preventDefault();
      setTarget(href);
    },
    push: (href: string) => (active ? setTarget(href) : router.push(href)),
    dialog: {
      target,
      onStay: () => setTarget(null),
      onLeave: () => {
        if (target) router.push(target);
        setTarget(null);
      },
    },
  };
}

type LeaveDialogProps = {
  target: string | null;
  onStay: () => void;
  onLeave: () => void;
  what: string;
};

export function LeaveDialog({ target, onStay, onLeave, what }: LeaveDialogProps) {
  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && onStay()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Leave with unsaved changes?</DialogTitle>
          <DialogDescription>
            Your draft of {what} isn&apos;t saved. It stays in this browser tab, and the editor
            offers it again when you come back to this topic.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={onStay}>
            Stay
          </Button>
          <Button onClick={onLeave}>Leave</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
