import { ScrollTextIcon } from "lucide-react";

import { FileUploadCard } from "@/components/dashboard/file-upload-card";
import type { MoodleFile } from "@/lib/moodle-files";

type SyllabusUploadProps = {
  files: File[];
  onFilesChange: (files: File[]) => void;
  moodleFiles: MoodleFile[];
  onRemoveMoodleFile: (id: string) => void;
};

export function SyllabusUpload(props: SyllabusUploadProps) {
  return (
    <FileUploadCard
      title="Syllabus"
      description="The course syllabus: topics, schedule and learning outcomes."
      icon={<ScrollTextIcon />}
      emptyTitle="No syllabus yet"
      accept=".pdf,.doc,.docx"
      {...props}
    />
  );
}
