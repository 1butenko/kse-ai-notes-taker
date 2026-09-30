import { BookOpenIcon } from "lucide-react";

import { FileUploadCard } from "@/components/dashboard/file-upload-card";
import type { SavedFile } from "@/lib/api";

type ReadingMaterialsUploadProps = {
  files: File[];
  onFilesChange: (files: File[]) => void;
  savedFiles: SavedFile[];
};

export function ReadingMaterialsUpload(props: ReadingMaterialsUploadProps) {
  return (
    <FileUploadCard
      title="Reading materials"
      icon={<BookOpenIcon />}
      emptyTitle="No reading materials yet"
      accept=".pdf,.doc,.docx,.ppt,.pptx"
      multiple
      {...props}
    />
  );
}
