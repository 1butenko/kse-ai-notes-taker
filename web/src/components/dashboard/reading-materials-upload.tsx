import { BookOpenIcon } from "lucide-react";

import { FileUploadCard } from "@/components/dashboard/file-upload-card";

export function ReadingMaterialsUpload() {
  return (
    <FileUploadCard
      title="Reading materials"
      description="Papers, book chapters and slides students read for the course."
      icon={<BookOpenIcon />}
      emptyTitle="No reading materials yet"
      emptyDescription="Upload PDF, Word or PowerPoint files. You can add several at once."
      accept=".pdf,.doc,.docx,.ppt,.pptx"
      multiple
    />
  );
}
