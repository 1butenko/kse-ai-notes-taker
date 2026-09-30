import { ScrollTextIcon } from "lucide-react";

import { FileUploadCard } from "@/components/dashboard/file-upload-card";
import type { SavedFile } from "@/lib/api";
import type { MoodleFile } from "@/lib/moodle-files";

type SyllabusUploadProps = {
  files: File[];
  onFilesChange: (files: File[]) => void;
  moodleFiles: MoodleFile[];
  onRemoveMoodleFile: (id: string) => void;
  savedFiles: SavedFile[];
};

export function SyllabusUpload(props: SyllabusUploadProps) {
  return (
    <FileUploadCard
      title="Syllabus"
      icon={<ScrollTextIcon />}
      emptyTitle="No syllabus yet"
      accept=".pdf,.doc,.docx"
      {...props}
    />
  );
}
