import path from "node:path/posix";
import type { ReviewableDoc } from "./scanner.js";
import { createFinding, type Finding } from "./findings.js";

type MarkdownLine = {
  text: string;
  number: number;
};

export function reviewDocumentWithStaticRules(doc: ReviewableDoc): Finding[] {
  if (!["markdown", "mdx", "unknown"].includes(doc.language)) {
    return [];
  }

  const content = doc.headContent ?? "";
  const lines = content.split(/\r?\n/).map((text, index) => ({
    text,
    number: index + 1
  }));

  return [
    ...findHeadingSkips(doc.path, lines),
    ...findMissingImageAltText(doc.path, lines),
    ...findBrokenRelativeLinks(doc, lines),
    ...findUnresolvedPlaceholders(doc.path, lines),
    ...findTodoMarkers(doc.path, lines),
    ...findDiscouragedTerms(doc.path, lines)
  ];
}

function findHeadingSkips(filePath: string, lines: MarkdownLine[]): Finding[] {
  const findings: Finding[] = [];
  let previousLevel = 0;

  for (const line of lines) {
    const match = /^(#{1,6})\s+\S/.exec(line.text);
    if (!match) continue;

    const level = match[1].length;
    if (previousLevel > 0 && level > previousLevel + 1) {
      const expectedLevel = previousLevel + 1;

      findings.push(
        createFinding({
          severity: "warning",
          category: "structure",
          path: filePath,
          startLine: line.number,
          title: "Heading level skips",
          explanation: `This heading jumps from H${previousLevel} to H${level}. Keep heading levels sequential so the exported document has a clean outline.`,
          confidence: "high",
          source: "rule",
          autofix: {
            kind: "replace-line",
            line: line.number,
            before: line.text,
            after: line.text.replace(/^#{1,6}/, "#".repeat(expectedLevel))
          }
        })
      );
    }

    previousLevel = level;
  }

  return findings;
}

function findMissingImageAltText(
  filePath: string,
  lines: MarkdownLine[]
): Finding[] {
  const findings: Finding[] = [];
  const imagePattern = /!\[\]\([^)]+\)/g;

  for (const line of lines) {
    if (!imagePattern.test(line.text)) continue;

    findings.push(
      createFinding({
        severity: "warning",
        category: "structure",
        path: filePath,
        startLine: line.number,
        title: "Image is missing alt text",
        explanation:
          "This image has empty alt text. Add short descriptive alt text so the exported document remains accessible.",
        confidence: "high",
        source: "rule"
      })
    );
  }

  return findings;
}

function findBrokenRelativeLinks(
  doc: ReviewableDoc,
  lines: MarkdownLine[]
): Finding[] {
  const findings: Finding[] = [];
  const linkPattern = /(?<!!)\[[^\]]+\]\(([^)#][^)]+)\)/g;

  for (const line of lines) {
    for (const match of line.text.matchAll(linkPattern)) {
      const rawHref = match[1].trim();
      if (isExternalOrAnchor(rawHref)) continue;
      if (rawHref.startsWith("mailto:")) continue;

      const cleanHref = rawHref.split("#")[0].split("?")[0];
      if (!cleanHref) continue;

      const resolved = path.normalize(path.join(path.dirname(doc.path), cleanHref));
      const suspicious =
        cleanHref.includes("missing") ||
        cleanHref.includes("not-found") ||
        resolved.startsWith("..");

      if (suspicious) {
        findings.push(
          createFinding({
            severity: "warning",
            category: "broken-link",
            path: doc.path,
            startLine: line.number,
            title: "Relative link needs verification",
            explanation: `This relative link points to \`${rawHref}\`, which looks likely to break from \`${doc.path}\`. Verify the target before merging.`,
            confidence: "medium",
            source: "link-checker"
          })
        );
      }
    }
  }

  return findings;
}

function findUnresolvedPlaceholders(
  filePath: string,
  lines: MarkdownLine[]
): Finding[] {
  const findings: Finding[] = [];
  const placeholderPattern = /\b(TBD|TODO_PLACEHOLDER|INSERT_[A-Z_]+|COMING SOON)\b/;

  for (const line of lines) {
    if (!placeholderPattern.test(line.text)) continue;

    findings.push(
      createFinding({
        severity: "blocker",
        category: "style",
        path: filePath,
        startLine: line.number,
        title: "Unresolved placeholder",
        explanation:
          "This line still contains placeholder text. Replace it before generating a polished export.",
        confidence: "high",
        source: "rule"
      })
    );
  }

  return findings;
}

function findTodoMarkers(filePath: string, lines: MarkdownLine[]): Finding[] {
  const findings: Finding[] = [];
  const todoPattern = /\b(TODO|FIXME)\b/i;

  for (const line of lines) {
    if (!todoPattern.test(line.text)) continue;

    findings.push(
      createFinding({
        severity: "suggestion",
        category: "style",
        path: filePath,
        startLine: line.number,
        title: "Draft marker in docs",
        explanation:
          "This line contains a TODO/FIXME marker. Keep draft notes out of docs that will be exported or released.",
        confidence: "high",
        source: "rule"
      })
    );
  }

  return findings;
}

type StyleTerm = {
  pattern: RegExp;
  advice: string;
  /**
   * Set only when swapping the term is a safe mechanical edit. Terms that need a
   * human to decide the wording stay advisory, so the app never invents prose.
   */
  replacement?: string;
};

const styleTerms: StyleTerm[] = [
  {
    pattern: /\butilize\b/i,
    advice: '"use"',
    replacement: "use"
  },
  {
    pattern: /\bclick here\b/i,
    advice: "link text that names the destination"
  }
];

function findDiscouragedTerms(filePath: string, lines: MarkdownLine[]): Finding[] {
  const findings: Finding[] = [];

  for (const line of lines) {
    for (const term of styleTerms) {
      if (!term.pattern.test(line.text)) continue;

      findings.push(
        createFinding({
          severity: "suggestion",
          category: "style",
          path: filePath,
          startLine: line.number,
          title: "Style guide wording",
          explanation: `Prefer ${term.advice} here. The comment should stay specific and easy for maintainers to accept.`,
          confidence: "medium",
          source: "rule",
          autofix: term.replacement
            ? {
                kind: "replace-line",
                line: line.number,
                before: line.text,
                after: replaceTermPreservingCase(
                  line.text,
                  term.pattern,
                  term.replacement
                )
              }
            : undefined
        })
      );
    }
  }

  return findings;
}

/**
 * Swaps every occurrence of a term on one line, matching the capitalisation the
 * author used so the fix does not introduce a casing error of its own.
 */
function replaceTermPreservingCase(
  text: string,
  pattern: RegExp,
  replacement: string
): string {
  const global = new RegExp(pattern.source, `${pattern.flags.replace("g", "")}g`);

  return text.replace(global, (match) =>
    startsUppercase(match)
      ? replacement.charAt(0).toUpperCase() + replacement.slice(1)
      : replacement
  );
}

function startsUppercase(value: string): boolean {
  const first = value.charAt(0);
  return first === first.toUpperCase() && first !== first.toLowerCase();
}

function isExternalOrAnchor(href: string): boolean {
  return (
    href.startsWith("#") ||
    href.startsWith("http://") ||
    href.startsWith("https://")
  );
}
