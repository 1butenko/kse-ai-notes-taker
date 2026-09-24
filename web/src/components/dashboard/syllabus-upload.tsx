import { ScrollTextIcon } from "lucide-react";

import { FileUploadCard } from "@/components/dashboard/file-upload-card";

export function SyllabusUpload() {
  return (
    <FileUploadCard
      title="Syllabus"
      description="The course syllabus: topics, schedule and learning outcomes."
      icon={<ScrollTextIcon />}
      emptyTitle="No syllabus yet"
      emptyDescription="Upload one PDF or Word document."
      accept=".pdf,.doc,.docx"
    />
  );
}
