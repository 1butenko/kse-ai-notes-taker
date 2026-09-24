import type { Section } from "@/lib/api";

export type MoodleFile = {
  id: string;
  name: string;
  filename: string;
  size: number;
  url: string;
};

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
        })),
    ),
  );
}
