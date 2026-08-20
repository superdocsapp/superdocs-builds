import { minimatch } from "minimatch";

export type ChangedFileStatus =
  | "added"
  | "modified"
  | "removed"
  | "renamed"
  | "changed"
  | "unchanged";

export type ChangedFile = {
  path: string;
  status: ChangedFileStatus;
  additions?: number;
  deletions?: number;
  patch?: string;
  headContent?: string;
  baseContent?: string;
};

export type ReviewableDoc = ChangedFile & {
  language: "markdown" | "mdx" | "rst" | "html" | "unknown";
};

const docsGlobs = [
  "**/*.md",
  "**/*.mdx",
  "**/*.rst",
  "README.md",
  "CHANGELOG.md",
  "docs/**"
];

const ignoredGlobs = [
  "**/node_modules/**",
  "**/dist/**",
  "**/build/**",
  "**/.next/**",
  "**/coverage/**",
  "**/*.png",
  "**/*.jpg",
  "**/*.jpeg",
  "**/*.gif",
  "**/*.webp",
  "**/*.pdf",
  "**/*.docx",
  "**/*.zip"
];

export function isDocumentationPath(path: string): boolean {
  const normalized = normalizePath(path);

  if (ignoredGlobs.some((pattern) => minimatch(normalized, pattern))) {
    return false;
  }

  return docsGlobs.some((pattern) =>
    minimatch(normalized, pattern, { nocase: true })
  );
}

export function filterReviewableDocs(files: ChangedFile[]): ReviewableDoc[] {
  return files
    .filter((file) => file.status !== "removed")
    .filter((file) => isDocumentationPath(file.path))
    .map((file) => ({
      ...file,
      language: detectDocLanguage(file.path)
    }));
}

export function detectDocLanguage(path: string): ReviewableDoc["language"] {
  const normalized = normalizePath(path).toLowerCase();

  if (normalized.endsWith(".md")) return "markdown";
  if (normalized.endsWith(".mdx")) return "mdx";
  if (normalized.endsWith(".rst")) return "rst";
  if (normalized.endsWith(".html")) return "html";
  if (normalized.startsWith("docs/")) return "unknown";

  return "unknown";
}

function normalizePath(path: string): string {
  return path.replaceAll("\\", "/").replace(/^\.?\//, "");
}

