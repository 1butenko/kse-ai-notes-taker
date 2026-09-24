"use client";

import { ScrollTextIcon } from "lucide-react";

import { FileUploadCard } from "@/components/dashboard/file-upload-card";
import { useMoodleCourse } from "@/components/dashboard/moodle-course-context";
import { findSyllabusFiles } from "@/lib/moodle-files";

export function SyllabusUpload() {
  const { imported } = useMoodleCourse();

  return (
    <FileUploadCard
      title="Syllabus"
      description="The course syllabus: topics, schedule and learning outcomes."
      icon={<ScrollTextIcon />}
      emptyTitle="No syllabus yet"
      accept=".pdf,.doc,.docx"
      moodleFiles={imported ? findSyllabusFiles(imported.sections) : []}
    />
  );
}
