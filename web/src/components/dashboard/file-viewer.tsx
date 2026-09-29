"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import { DownloadIcon } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { fileName, fileUrl } from "@/lib/api";

type Viewing = { path: string; page?: number; title?: string };

const FileViewerContext = createContext<((viewing: Viewing) => void) | null>(null);

/** Opens uploaded files and excerpts in a modal: PDFs inline, other types as a download. */
export function FileViewerProvider({ children }: { children: ReactNode }) {
  const [viewing, setViewing] = useState<Viewing | null>(null);
  const isPdf = viewing ? /\.pdf$/i.test(viewing.path) : false;

  return (
    <FileViewerContext.Provider value={setViewing}>
      {children}
      <Dialog open={viewing !== null} onOpenChange={(open) => !open && setViewing(null)}>
        <DialogContent className="flex h-[90vh] flex-col sm:max-w-5xl">
          {viewing && (
            <>
              <DialogHeader className="pr-8">
                <DialogTitle className="truncate">
                  {viewing.title ?? fileName(viewing.path)}
                  {viewing.page && (
                    <span className="font-normal text-muted-foreground">
                      {" "}
                      · PDF page {viewing.page}
                    </span>
                  )}
                </DialogTitle>
              </DialogHeader>
              {isPdf ? (
                <iframe
                  // Re-mount per page: changing only the #page hash doesn't scroll the viewer.
                  key={`${viewing.path}#${viewing.page ?? ""}`}
                  src={fileUrl(viewing.path, viewing.page)}
                  title={fileName(viewing.path)}
                  className="min-h-0 w-full flex-1 rounded-lg border"
                />
              ) : (
                <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
                  <p className="text-muted-foreground">
                    This file type can&apos;t be previewed in the browser.
                  </p>
                  <a href={fileUrl(viewing.path)} download className={buttonVariants()}>
                    <DownloadIcon />
                    Download {fileName(viewing.path)}
                  </a>
                </div>
              )}
            </>
          )}
        </DialogContent>
      </Dialog>
    </FileViewerContext.Provider>
  );
}

export function useFileViewer() {
  const open = useContext(FileViewerContext);
  if (!open) throw new Error("useFileViewer must be used inside FileViewerProvider");
  return open;
}
