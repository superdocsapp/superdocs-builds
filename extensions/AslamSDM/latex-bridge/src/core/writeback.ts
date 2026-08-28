export interface TexSegment {
  file: string;
  index: number;
  start: number;
  end: number;
  text: string;
}

export interface AlignedChunk {
  chunkId: string;
  file: string;
  segmentIndex: number;
  start: number;
  end: number;
}

export interface ChangePatch {
  changeId: string;
  chunkId: string;
  operation: "edit" | "insert";
  file: string;
  start: number;
  end: number;
  replacement: string;
}

export interface PatchResult {
  files: Map<string, string>;
  applied: ChangePatch[];
  unresolved: string[];
}

/**
 * Split .tex content into paragraph-like segments at blank lines.
 * Offsets are byte offsets into `content`; segments cover their own text
 * with no trailing newline, so (start,end) ranges are splice-safe.
 */
export function segmentize(content: string): TexSegment[] {
  const segments: TexSegment[] = [];
  const lines = content.split("\n");
  let start = 0;
  let buf: string[] = [];
  let bufStart = 0;

  const flush = () => {
    if (buf.length === 0) return;
    const text = buf.join("\n");
    segments.push({
      file: "",
      index: segments.length,
      start: bufStart,
      end: bufStart + text.length,
      text,
    });
    buf = [];
  };

  for (let i = 0; i < lines.length; i++) {
    if (lines[i].trim() === "") {
      flush();
    } else {
      if (buf.length === 0) {
        bufStart = start;
      }
      buf.push(lines[i]);
    }
    start += lines[i].length + 1;
  }
  flush();
  return segments;
}

export function normalize(text: string): string {
  return text
    .replace(/\\[a-zA-Z]+\*?/g, " ")
    .replace(/[{}]/g, " ")
    .replace(/[$]/g, " ")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

/**
 * Best-fit a chunk (as normalized word list) to a segment via ordered
 * subsequence scoring; require at least 70% coverage.
 */
export function alignChunkToSegments(
  chunkWords: string[],
  segments: TexSegment[]
): TexSegment | undefined {
  if (chunkWords.length === 0) return undefined;
  let best: TexSegment | undefined;
  let bestScore = 0;
  for (const seg of segments) {
    const segWords = normalize(seg.text).split(" ").filter(Boolean);
    if (segWords.length === 0) continue;
    const score = subsequenceScore(chunkWords, segWords);
    if (score > bestScore) {
      bestScore = score;
      best = seg;
    }
  }
  return bestScore >= 0.7 ? best : undefined;
}

function subsequenceScore(query: string[], corpus: string[]): number {
  let i = 0;
  let hits = 0;
  for (const w of corpus) {
    if (i < query.length && w === query[i]) {
      hits += 1;
      i += 1;
    }
  }
  return hits / query.length;
}

function decode(text: string): string {
  return text
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&nbsp;/g, " ");
}

/**
 * Convert SuperDocs chunk HTML back to LaTeX source text. Math (data-latex)
 * is lossless (inline wrapped in $...$, block in \[...\]); citations become
 * \cite{...}; footnote refs inline the footnote body as \footnote{...};
 * headings become \section/\subsection. Best-effort: unknown constructs
 * degrade to their visible text. Atomic spans (math/cite/footnote) are
 * replaced before the tag walk so their inner renderings are not duplicated.
 */
export function htmlToLatex(html: string, footnotes: string[]): string {
  const mathRe = /<span[^>]*data-latex="([^"]*)"[^>]*>[\s\S]*?<\/span>/gi;
  const citeRe = /<span[^>]*data-citation="([^"]*)"[^>]*>[\s\S]*?<\/span>/gi;
  const fnRe = /<sup[^>]*data-footnote-ref="(\d+)"[^>]*>[\s\S]*?<\/sup>/gi;
  const placeholder = "\uE000";
  const placeholderEnd = "\uE001";
  let h = html
    .replace(mathRe, (m, latex: string) => {
      const block = /\bdata-type="block-math"/.test(m);
      const body = decode(latex).trim();
      return block ? `${placeholder}\\[${body}\\]${placeholderEnd}` : `${placeholder}$${body}$${placeholderEnd}`;
    })    .replace(citeRe, (m, keys: string) => `${placeholder}\\cite{${keys}}${placeholderEnd}`)
    .replace(fnRe, (m, n: string) => {
      const idx = parseInt(n, 10) - 1;
      const body = footnotes[idx] ?? "";
      return `${placeholder}\\footnote{${htmlToLatex(body, [])}}${placeholderEnd}`;
    });

  const out: string[] = [];
  const tokenRe = new RegExp(`${placeholder}[\\s\\S]*?${placeholderEnd}`, "g");

  function walk(h: string): void {
    const re = /<([a-z0-9]+)([^>]*?)\/?>|<\/([a-z0-9]+)>/gi;
    let last = 0;
    const pushText = (t: string) => {
      if (t.includes(placeholder)) {
        let last = 0;
        for (const m of t.matchAll(tokenRe)) {
          out.push(decode(t.slice(last, m.index)));
          out.push(m[0].slice(1, m[0].length - 1));
          last = m.index + m[0].length;
        }
        out.push(decode(t.slice(last)));
      } else if (t) {
        out.push(decode(t));
      }
    };
    for (let m = re.exec(h); m; m = re.exec(h)) {
      pushText(h.slice(last, m.index));
      last = m.index + m[0].length;
      const tag = (m[1] || m[3]).toLowerCase();
      if (m[2] !== undefined) {
        const attrs = m[2];
        const latex = /data-latex="([^"]*)"/i.exec(attrs);
        if (latex) continue;
        const cite = /data-citation="([^"]*)"/i.exec(attrs);
        if (cite && tag === "span") continue;
        const fn = /data-footnote-ref="(\d+)"/i.exec(attrs);
        if (fn && tag === "sup") continue;
        switch (tag) {
          case "p":
            out.push("\n\n");
            break;
          case "h1":
            out.push("\n\n\\section{");
            break;
          case "h2":
            out.push("\n\n\\subsection{");
            break;
          case "h3":
            out.push("\n\n\\subsubsection{");
            break;
          case "strong":
            out.push("\\textbf{");
            break;
          case "em":
            out.push("\\emph{");
            break;
          case "blockquote":
            out.push("\n\n\\begin{quote}\n");
            break;
          default:
            break;
        }
      } else {
        switch (tag) {
          case "h1":
          case "h2":
          case "h3":
            out.push("}");
            break;
          case "strong":
            out.push("}");
            break;
          case "em":
            out.push("}");
            break;
          case "blockquote":
            out.push("\n\\end{quote}");
            break;
          default:
            break;
        }
      }
    }
    pushText(h.slice(last));
  }

  walk(h);
  return out.join("").replace(/(\\subsubsection\{|\\subsection\{|\\section\{)(\d+)\s+/, "$1");
}