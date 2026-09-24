"use client";

import { useState } from "react";
import { DownloadIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { SidebarMenuButton } from "@/components/ui/sidebar";

export function MoodleImportDialog() {
  const [open, setOpen] = useState(false);
  const [token, setToken] = useState("");

  const onSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setOpen(false);
  };

  return (
    <>
      <SidebarMenuButton tooltip="Import from Moodle" onClick={() => setOpen(true)}>
        <DownloadIcon />
        <span>Import from Moodle</span>
      </SidebarMenuButton>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <form onSubmit={onSubmit} className="flex flex-col gap-6">
            <DialogHeader>
              <DialogTitle>Import from Moodle</DialogTitle>
              <DialogDescription>
                Paste your Moodle token to import course materials.
              </DialogDescription>
            </DialogHeader>

            <Field>
              <FieldLabel htmlFor="moodle-token">Moodle token</FieldLabel>
              <Input
                id="moodle-token"
                type="password"
                autoComplete="off"
                placeholder="Paste your token"
                value={token}
                onChange={(event) => setToken(event.target.value)}
                autoFocus
              />
            </Field>

            <DialogFooter>
              <DialogClose render={<Button type="button" variant="outline" />}>
                Cancel
              </DialogClose>
              <Button type="submit" disabled={!token.trim()}>
                <DownloadIcon />
                Import
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
