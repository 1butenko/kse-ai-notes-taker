import type { Module, ModuleContent, Section } from "@/lib/api";

export type MoodleFile = {
  id: string;
  kind: "file" | "link";
  moduleId: number;
  name: string;
  filename: string;
  size: number;
  url: string;
  fileurl: string;
  saveAs: string;
};

export type MoodleSectionFiles = {
  title: string;
  files: MoodleFile[];
};

function saveAsName(title: string, filename: string): string {
  const extension = filename.match(/\.[^.]+$/)?.[0] ?? "";
  return title.toLowerCase().endsWith(extension.toLowerCase()) ? title : `${title}${extension}`;
}

function toMoodleFile(module: Module, content: ModuleContent): MoodleFile {
  const single = module.contents.filter((c) => c.type === "file").length === 1;
  return {
    id: `${module.id}/${content.filename}`,
    kind: "file",
    moduleId: module.id,
    name: single ? module.name : `${module.name}: ${content.filename}`,
    filename: content.filename,
    size: content.filesize,
    url: module.url,
    fileurl: content.fileurl,
    saveAs: single ? saveAsName(module.name, content.filename) : content.filename,
  };
}

const SYLLABUS = /syllabus|силабус/iu;

const isSyllabus = (module: Module, content: ModuleContent) =>
  SYLLABUS.test(module.name) || SYLLABUS.test(content.filename);

export function findSyllabusFiles(sections: Section[]): MoodleFile[] {
  return sections.flatMap((section) =>
    section.modules.flatMap((module) =>
      module.contents
        .filter((content) => content.type === "file" && isSyllabus(module, content))
        .map((content) => toMoodleFile(module, content)),
    ),
  );
}

const READABLE = /\.(pdf|docx?|pptx?|md|txt)$/i;
const VIDEO = /^https?:\/\/([^/]+\.)?(youtube\.com|youtu\.be|vimeo\.com)\//i;

/** A Moodle link to a web page; the API saves it as text, or as a PDF if it serves one. */
function toMoodleLink(module: Module, content: ModuleContent): MoodleFile {
  const safe = module.name.replace(/[/\\]/g, "-").trim();
  return {
    id: `${module.id}/link`,
    kind: "link",
    moduleId: module.id,
    name: module.name,
    filename: content.fileurl,
    size: 0,
    url: module.url,
    fileurl: content.fileurl,
    saveAs: `${safe}${/\.pdf$/i.test(new URL(content.fileurl).pathname) ? ".pdf" : ".md"}`,
  };
}

const isWebPage = (module: Module, content: ModuleContent) =>
  module.modname === "url" &&
  content.type === "url" &&
  /^https?:\/\//i.test(content.fileurl) &&
  !VIDEO.test(content.fileurl);

/** The course's readable files other than syllabi, and its links to web pages (not videos),
 * by Moodle section. */
export function findMaterialFiles(sections: Section[]): MoodleSectionFiles[] {
  return sections
    .map((section, index) => ({
      title: section.name || `Section ${index}`,
      files: section.modules.flatMap((module) => {
        const link = module.contents.find((content) => isWebPage(module, content));
        if (link) return [toMoodleLink(module, link)];
        return module.contents
          .filter(
            (content) =>
              content.type === "file" &&
              READABLE.test(content.filename) &&
              !isSyllabus(module, content),
          )
          .map((content) => toMoodleFile(module, content));
      }),
    }))
    .filter((section) => section.files.length > 0);
}
