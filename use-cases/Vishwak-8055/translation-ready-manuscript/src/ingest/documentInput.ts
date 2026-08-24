import { inflateRawSync, inflateSync } from "node:zlib";
import { TextDecoder } from "node:util";
import { parse as parseHtml } from "node-html-parser";

export type SupportedDocumentFormat = "txt" | "md" | "docx" | "pdf" | "html";

export interface DocumentInput {
  filename: string;
  format: SupportedDocumentFormat;
  rawText: string;
  sourceBytes: number;
}

export function detectDocumentFormat(filename: string): SupportedDocumentFormat {
  const extension = filename.toLowerCase().split(".").pop() ?? "";
  if (extension === "txt" || extension === "text") return "txt";
  if (extension === "md" || extension === "markdown") return "md";
  if (extension === "docx") return "docx";
  if (extension === "pdf") return "pdf";
  if (extension === "html" || extension === "htm") return "html";
  throw new Error(`Unsupported manuscript format '.${extension || "unknown"}'. Supported formats: .txt, .md, .docx, .pdf, .html.`);
}

function readU16(bytes: Uint8Array, offset: number): number {
  return bytes[offset]! | (bytes[offset + 1]! << 8);
}

function readU32(bytes: Uint8Array, offset: number): number {
  return (bytes[offset]! | (bytes[offset + 1]! << 8) | (bytes[offset + 2]! << 16) | (bytes[offset + 3]! << 24)) >>> 0;
}

/** Minimal ZIP reader for DOCX packages. Supports stored and deflated entries; no third-party ZIP dependency required. */
function readZipEntry(bytes: Uint8Array, wantedName: string): Uint8Array {
  const decoder = new TextDecoder("utf-8");
  for (let offset = 0; offset <= bytes.length - 46; offset++) {
    if (readU32(bytes, offset) !== 0x02014b50) continue;
    const compression = readU16(bytes, offset + 10);
    const compressedSize = readU32(bytes, offset + 20);
    const nameLength = readU16(bytes, offset + 28);
    const extraLength = readU16(bytes, offset + 30);
    const commentLength = readU16(bytes, offset + 32);
    const localOffset = readU32(bytes, offset + 42);
    const name = decoder.decode(bytes.slice(offset + 46, offset + 46 + nameLength));
    if (name !== wantedName) {
      offset += 45 + nameLength + extraLength + commentLength;
      continue;
    }
    if (localOffset + 30 > bytes.length || readU32(bytes, localOffset) !== 0x04034b50) {
      throw new Error(`Invalid DOCX ZIP entry for ${wantedName}.`);
    }
    const localNameLength = readU16(bytes, localOffset + 26);
    const localExtraLength = readU16(bytes, localOffset + 28);
    const dataStart = localOffset + 30 + localNameLength + localExtraLength;
    const compressed = bytes.slice(dataStart, dataStart + compressedSize);
    if (compression === 0) return compressed;
    if (compression === 8) return new Uint8Array(inflateRawSync(compressed));
    throw new Error(`Unsupported DOCX compression method ${compression}.`);
  }
  throw new Error(`DOCX is missing ${wantedName}.`);
}

function decodePdfLiteral(value: string): string {
  return value
    .replace(/\\([\\()\\])/g, "$1")
    .replace(/\\n/g, "\n")
    .replace(/\\r/g, "\r")
    .replace(/\\t/g, "\t")
    .replace(/\\b/g, "\b")
    .replace(/\\f/g, "\f");
}

function ascii85Decode(input: string): Uint8Array<ArrayBuffer> {
  const clean = input.replace(/\s+/g, "").replace(/<~|~>/g, "");
  const output: number[] = [];
  let group: number[] = [];
  const flush = (partial = false): void => {
    if (group.length === 0) return;
    const count = group.length;
    while (group.length < 5) group.push(84);
    let value = 0;
    for (const digit of group) value = value * 85 + digit;
    const bytes = [(value >>> 24) & 255, (value >>> 16) & 255, (value >>> 8) & 255, value & 255];
    output.push(...bytes.slice(0, partial ? count - 1 : 4));
    group = [];
  };
  for (const ch of clean) {
    if (ch === "z" && group.length === 0) { output.push(0, 0, 0, 0); continue; }
    const code = ch.charCodeAt(0) - 33;
    if (code < 0 || code > 84) continue;
    group.push(code);
    if (group.length === 5) flush();
  }
  if (group.length) flush(true);
  const decoded = new Uint8Array(output.length);
  decoded.set(output);
  return decoded;
}

function extractPdfText(bytes: Uint8Array): string {
  const latin1 = new TextDecoder("latin1");
  const source = latin1.decode(bytes);
  const chunks: string[] = [];
  const streamRe = /<<([\s\S]*?)>>\s*stream\r?\n([\s\S]*?)endstream/g;
  for (const match of source.matchAll(streamRe)) {
    const dictionary = match[1] ?? "";
    const rawStream = match[2] ?? "";
    let streamText = rawStream;
    if (/\/FlateDecode\b/.test(dictionary)) {
      const streamStart = match.index! + match[0].indexOf(rawStream);
      let encoded = bytes.slice(streamStart, streamStart + rawStream.length);
      if (/\/ASCII85Decode\b/.test(dictionary)) { const decoded = ascii85Decode(latin1.decode(encoded)); const copy = new Uint8Array(new ArrayBuffer(decoded.byteLength)); copy.set(decoded); encoded = copy; }
      try {
        streamText = latin1.decode(inflateSync(encoded));
      } catch {
        try {
          streamText = latin1.decode(inflateRawSync(encoded));
        } catch {
          continue;
        }
      }
    }

    for (const m of streamText.matchAll(/\(((?:\\.|[^\\)])*)\)\s*T[Jj]/g)) {
      chunks.push(decodePdfLiteral(m[1] ?? ""));
    }
    for (const m of streamText.matchAll(/\[((?:\\.|[^\]])*)\]\s*TJ/g)) {
      const parts = m[1]?.match(/\(((?:\\.|[^\\)])*)\)/g) ?? [];
      chunks.push(parts.map((part) => decodePdfLiteral(part.slice(1, -1))).join(""));
    }
  }

  const text = chunks.join("\n").replace(/[ \t]+/g, " ").replace(/\n{3,}/g, "\n\n").trim();
  if (!text) throw new Error("The PDF contains no extractable text. Scanned/image-only PDFs require OCR and are not silently processed.");
  return text;
}

function decodeXml(value: string): string {
  return value
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, "&");
}

function xmlTextToMarkdown(xml: string): string {
  const paragraphs = xml.match(/<w:p(?:\s[^>]*)?>[\s\S]*?<\/w:p>/g) ?? [];
  const output: string[] = [];
  for (const paragraph of paragraphs) {
    const styleMatch = paragraph.match(/<w:pStyle[^>]*w:val=["']([^"']+)["'][^>]*\/>/);
    const style = styleMatch?.[1]?.toLowerCase() ?? "";
    const runs = paragraph.match(/<w:r(?:\s[^>]*)?>[\s\S]*?<\/w:r>/g) ?? [];
    let text = "";
    for (const run of runs) {
      const values = [...run.matchAll(/<w:t(?:\s[^>]*)?>([\s\S]*?)<\/w:t>/g)].map((m) => decodeXml(m[1] ?? ""));
      const value = values.join("");
      if (!value) continue;
      const italic = /<w:i(?:\s[^>]*)?\/?\s*>/.test(run);
      const bold = /<w:b(?:\s[^>]*)?\/?\s*>/.test(run);
      text += italic ? `_${value}_` : bold ? `**${value}**` : value;
    }
    if (!text.trim()) continue;
    if (style.includes("heading1") || style.includes("title")) output.push(`# ${text.trim()}`);
    else if (style.includes("heading2") || style.includes("heading3")) output.push(`## ${text.trim()}`);
    else output.push(text.trim());
  }
  return output.join("\n\n").trim();
}

export function parseDocumentInput(filename: string, bytes: Uint8Array): DocumentInput {
  const format = detectDocumentFormat(filename);
  if (format === "docx") {
    const documentXml = new TextDecoder("utf-8").decode(readZipEntry(bytes, "word/document.xml"));
    const rawText = xmlTextToMarkdown(documentXml);
    if (!rawText) throw new Error("The DOCX contains no readable paragraph text.");
    return { filename, format, rawText, sourceBytes: bytes.byteLength };
  }
  if (format === "pdf") {
    return { filename, format, rawText: extractPdfText(bytes), sourceBytes: bytes.byteLength };
  }
  if (format === "html") {
    const root = parseHtml(new TextDecoder("utf-8").decode(bytes));
    const blocks: string[] = [];
    for (const node of root.querySelectorAll("h1, h2, h3, p, li, blockquote")) {
      const text = node.textContent.replace(/\s+/g, " ").trim();
      if (!text) continue;
      const tag = node.tagName.toLowerCase();
      blocks.push(tag === "h1" ? `# ${text}` : tag === "h2" || tag === "h3" ? `## ${text}` : text);
    }
    const rawText = blocks.join("\n\n").trim();
    if (!rawText) throw new Error("The HTML document contains no readable manuscript text.");
    return { filename, format, rawText, sourceBytes: bytes.byteLength };
  }
  const rawText = new TextDecoder("utf-8", { fatal: false }).decode(bytes).replace(/^\uFEFF/, "");
  if (!rawText.trim()) throw new Error("The uploaded manuscript is empty.");
  return { filename, format, rawText, sourceBytes: bytes.byteLength };
}
