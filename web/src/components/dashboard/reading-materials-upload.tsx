import { BookOpenIcon } from "lucide-react";

import { FileUploadCard } from "@/components/dashboard/file-upload-card";

type ReadingMaterialsUploadProps = {
  files: File[];
  onFilesChange: (files: File[]) => void;
};

export function ReadingMaterialsUpload(props: ReadingMaterialsUploadProps) {
  return (
    <FileUploadCard
      title="Reading materials"
      description="Papers, book chapters and slides students read for the course."
      icon={<BookOpenIcon />}
      emptyTitle="No reading materials yet"
      accept=".pdf,.doc,.docx,.ppt,.pptx"
      multiple
      {...props}
    />
  );
}
