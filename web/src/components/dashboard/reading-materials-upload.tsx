import { BookOpenIcon } from "lucide-react";

import { FileUploadCard } from "@/components/dashboard/file-upload-card";
import { MoodleMaterialsDialog } from "@/components/dashboard/moodle-materials-dialog";
import { fileName, type SavedFile } from "@/lib/api";
import type { MoodleFile, MoodleSectionFiles } from "@/lib/moodle-files";

type ReadingMaterialsUploadProps = {
  files: File[];
  onFilesChange: (files: File[]) => void;
  savedFiles: SavedFile[];
  moodleSections: MoodleSectionFiles[] | null;
  moodleFiles: MoodleFile[];
  selectedMoodleIds: Set<string>;
  onSelectMoodleFiles: (ids: Set<string>) => void;
};

export function ReadingMaterialsUpload({
  moodleSections,
  selectedMoodleIds,
  onSelectMoodleFiles,
  ...props
}: ReadingMaterialsUploadProps) {
  return (
    <FileUploadCard
      title="Reading materials"
      icon={<BookOpenIcon />}
      emptyTitle="No reading materials yet"
      accept=".pdf,.doc,.docx,.ppt,.pptx"
      multiple
      onRemoveMoodleFile={(id) => {
        const next = new Set(selectedMoodleIds);
        next.delete(id);
        onSelectMoodleFiles(next);
      }}
      actions={
        <MoodleMaterialsDialog
          sections={moodleSections}
          selected={selectedMoodleIds}
          saved={new Set(props.savedFiles.map((file) => fileName(file.path)))}
          onSelect={onSelectMoodleFiles}
        />
      }
      {...props}
    />
  );
}
