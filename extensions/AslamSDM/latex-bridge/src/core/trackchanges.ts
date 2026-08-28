import JSZip from "jszip";
import { Change } from "./align";

export interface TrackChange {
  id: string;
  author: string;
  date?: string;
  oldText: string;
  newText: string;
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

interface ParagraphRuns {
  /** runs in document order: { kind: "orig" | "ins" | "del", text } */
  runs: { kind: "orig" | "ins" | "del"; text: string }[];
  insId: string;
  author: string;
  date?: string;
}

function extractRuns(pXml: string): ParagraphRuns {
  const runs: { kind: "orig" | "ins" | "del"; text: string }[] = [];
  let insId = "";
  let author = "";
  let date: string | undefined;
  const pickMeta = (tag: "w:ins" | "w:del") => {
    const re = new RegExp(`<${tag}\\b([^>]*)>`, "g");
    for (let m = re.exec(pXml); m; m = re.exec(pXml)) {
      const a = /w:author="([^"]*)"/.exec(m[1]);
      const d = /w:date="([^"]*)"/.exec(m[1]);
      const id = /w:id="([^"]*)"/.exec(m[1]);
      if (a && !author) author = a[1];
      if (d && !date) date = d[1];
      if (id) insId = id[1];
    }
  };
  pickMeta("w:ins");
  pickMeta("w:del");
  const combined = /<w:ins\b[^>]*>[\s\S]*?<\/w:ins>|<w:del\b[^>]*>[\s\S]*?<\/w:del>|<w:r\b[^>]*>[\s\S]*?<\/w:r>/g;
  for (let m = combined.exec(pXml); m; m = combined.exec(pXml)) {
    if (m[0].startsWith("<w:ins")) {
      push("ins", m[0]);
    } else if (m[0].startsWith("<w:del")) {
      push("del", m[0]);
    } else {
      push("orig", m[0]);
    }
  }
  return { runs, insId, author, date };

  function push(kind: "orig" | "ins" | "del", xml: string) {
    const text = collectText(xml);
    if (text) runs.push({ kind, text });
  }
}

function collectText(xml: string): string {
  const out: string[] = [];
  const re = /<w:t\b[^>]*>([\s\S]*?)<\/w:t>|<w:delText\b[^>]*>([\s\S]*?)<\/w:delText>|<w:br\b[^>]*\/>|<w:tab\b[^>]*\/>/g;
  for (let m = re.exec(xml); m; m = re.exec(xml)) {
    if (m[0].startsWith("<w:br") || m[0].startsWith("<w:tab")) out.push(" ");
    else out.push(m[1] ?? m[2] ?? "");
  }
  return out.join("");
}

function render(runs: { kind: "orig" | "ins" | "del"; text: string }[], kind: "old" | "new"): string {
  const keepIns = kind === "new";
  const keepDel = kind === "old";
  let out = "";
  for (const r of runs) {
    if (r.kind === "ins" && keepIns) out += r.text;
    else if (r.kind === "del" && keepDel) out += r.text;
    else if (r.kind === "orig") out += r.text;
  }
  return out;
}

export async function parseDocxTrackChanges(docxBytes: Uint8Array): Promise<TrackChange[]> {
  const zip = await JSZip.loadAsync(docxBytes);
  const doc = zip.file("word/document.xml");
  if (!doc) return [];
  const xml = await doc.async("string");
  const out: TrackChange[] = [];
  const pRe = /<w:p\b[^>]*>([\s\S]*?)<\/w:p>/g;
  for (let m = pRe.exec(xml); m; m = pRe.exec(xml)) {
    const { runs, insId, author, date } = extractRuns(m[1]);
    if (runs.some((r) => r.kind === "ins" || r.kind === "del")) {
      out.push({
        id: insId || `tc-${out.length}`,
        author,
        date,
        oldText: render(runs, "old"),
        newText: render(runs, "new"),
      });
    }
  }
  return out;
}

/** Convert a tracked-change paragraph to a Change for the write-back planner. */
export function toChange(tc: TrackChange): Change {
  return {
    change_id: tc.id,
    chunk_id: tc.id,
    operation: "edit",
    old_html: `<p>${escapeHtml(tc.oldText)}</p>`,
    new_html: `<p>${escapeHtml(tc.newText)}</p>`,
  };
}
