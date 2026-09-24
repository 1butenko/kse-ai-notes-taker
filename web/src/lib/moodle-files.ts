import type { Section } from "@/lib/api";

export type MoodleFile = {
  id: string;
  name: string;
  filename: string;
  size: number;
  url: string;
  fileurl: string;
  saveAs: string;
};

function saveAsName(title: string, filename: string): string {
  const extension = filename.match(/\.[^.]+$/)?.[0] ?? "";
  return title.toLowerCase().endsWith(extension.toLowerCase()) ? title : `${title}${extension}`;
}

const SYLLABUS = /syllabus|силабус/iu;

export function findSyllabusFiles(sections: Section[]): MoodleFile[] {
  return sections.flatMap((section) =>
    section.modules.flatMap((module) =>
      module.contents
        .filter(
          (content) =>
            content.type === "file" &&
            (SYLLABUS.test(module.name) || SYLLABUS.test(content.filename)),
        )
        .map((content) => ({
          id: `${module.id}/${content.filename}`,
          name: module.name,
          filename: content.filename,
          size: content.filesize,
          url: module.url,
          fileurl: content.fileurl,
          saveAs: saveAsName(module.name, content.filename),
        })),
    ),
  );
}
