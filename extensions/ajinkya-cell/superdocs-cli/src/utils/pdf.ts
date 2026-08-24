import zlib from 'zlib';

/**
 * Adobe ASCII85 / Base85 Decoder
 * Conforms to Adobe PostScript & PDF ASCII85Decode specification.
 */
export function decodeAscii85(str: string): Buffer {
  let clean = str.replace(/<~|\s/g, '');
  if (clean.endsWith('~>')) {
    clean = clean.slice(0, -2);
  }
  const bytes: number[] = [];

  for (let i = 0; i < clean.length; i += 5) {
    const chunk = clean.slice(i, i + 5);
    if (chunk === 'z') {
      bytes.push(0, 0, 0, 0);
      i -= 4; // 'z' represents 4 zero bytes
      continue;
    }

    let value = 0;
    const pad = 5 - chunk.length;
    const paddedChunk = chunk + 'u'.repeat(pad);

    for (let j = 0; j < 5; j++) {
      value = value * 85 + (paddedChunk.charCodeAt(j) - 33);
    }

    const b0 = (value >>> 24) & 255;
    const b1 = (value >>> 16) & 255;
    const b2 = (value >>> 8) & 255;
    const b3 = value & 255;

    const quad = [b0, b1, b2, b3];
    for (let k = 0; k < 4 - pad; k++) {
      bytes.push(quad[k]);
    }
  }

  return Buffer.from(bytes);
}

/**
 * Standalone Multi-Filter PDF Text Extractor and Parser
 * Handles /ASCII85Decode, /FlateDecode, chained filter arrays, and uncompressed PDF text operators.
 */
export function parsePdfToMarkdown(buffer: Buffer, fallbackName = 'Document'): string {
  const str = buffer.toString('latin1');
  const streamBlocks = [...str.matchAll(/<<([\s\S]*?)>>\s*stream\r?\n([\s\S]*?)(?:~>)?endstream/g)];

  const rawLines: string[] = [];

  for (const block of streamBlocks) {
    const dict = block[1];
    const streamData = block[2];

    let decompressed = '';
    try {
      let curBuffer: Buffer;
      if (dict.includes('ASCII85Decode')) {
        curBuffer = decodeAscii85(streamData);
      } else {
        curBuffer = Buffer.from(streamData, 'latin1');
      }

      if (dict.includes('FlateDecode')) {
        curBuffer = zlib.inflateSync(curBuffer);
      }
      decompressed = curBuffer.toString('latin1');
    } catch {
      try {
        decompressed = zlib.inflateSync(Buffer.from(streamData, 'latin1')).toString('latin1');
      } catch {
        decompressed = streamData;
      }
    }

    if (!decompressed) continue;

    const btBlocks = decompressed.match(/BT[\s\S]*?ET/g) || [decompressed];

    for (const bt of btBlocks) {
      const lines = bt.split(/\r?\n/);
      for (const line of lines) {
        // Match ( ... ) Tj
        const tjMatch = line.match(/\(((?:\\\(|\\\)|[^)])*)\)\s*Tj/);
        if (tjMatch) {
          const t = cleanPdfText(tjMatch[1]);
          if (t) rawLines.push(t);
        }

        // Match [ ... ] TJ
        const tjArrayMatch = line.match(/\[(.*?)\]\s*TJ/);
        if (tjArrayMatch) {
          const inner = tjArrayMatch[1];
          let combined = '';
          const tokens = inner.match(/\((?:\\\(|\\\)|[^)])*\)|-?\d+(?:\.\d+)?/g) || [];
          for (const token of tokens) {
            if (token.startsWith('(') && token.endsWith(')')) {
              combined += cleanPdfText(token.slice(1, -1));
            } else {
              const num = parseFloat(token);
              if (num < -50) combined += ' ';
            }
          }
          if (combined.trim()) rawLines.push(combined.trim());
        }
      }
    }
  }

  function cleanPdfText(text: string): string {
    return text
      .replace(/\\([0-7]{3})/g, (_, oct) => {
        const code = parseInt(oct, 8);
        if (code === 40) return '(';
        if (code === 41) return ')';
        if (code === 127 || code === 21 || code === 25 || code === 17) return '• ';
        return String.fromCharCode(code);
      })
      .replace(/\\([()\\])/g, '$1')
      .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g, ' ')
      .trim();
  }

  if (rawLines.length === 0) {
    const asciiMatches = str.match(/[A-Za-z0-9 ,.:;@\-_/()'\"]{4,}/g) || [];
    const validLines = asciiMatches.filter(l => !l.includes('obj') && !l.includes('endobj') && !l.includes('stream') && !l.includes('Font') && !l.includes('MediaBox'));
    if (validLines.length > 5) {
      return validLines.join('\n');
    }
    return `# ${fallbackName}\n\nDocument loaded for editing.`;
  }

  const markdownLines: string[] = [];
  const knownHeaders = [
    'education', 'projects', 'experience', 'skills', 'technical skills',
    'certifications', 'achievements', 'summary', 'about', 'work experience',
    'application overview', 'core functionalities', 'file structure',
    'architecture notes', 'table of contents', 'overview'
  ];

  for (let i = 0; i < rawLines.length; i++) {
    const item = rawLines[i];
    if (!item) continue;
    if (item === '•' || item === 'n' || item === 'nnn') continue;

    // Numbered headings e.g. "1. Overview", "2. Core Functionalities"
    if (/^\d+\.\s+[A-Za-z]/.test(item)) {
      markdownLines.push(`\n## ${item}\n`);
    } else if (knownHeaders.some(h => item.toLowerCase() === h || item.toLowerCase() === `## ${h}`) && item.length < 50) {
      markdownLines.push(`\n## ${item}\n`);
    } else if (item.startsWith('•')) {
      markdownLines.push(`- ${item.replace(/^•\s*/, '')}`);
    } else if (i === 0 && !item.startsWith('#')) {
      markdownLines.push(`# ${item}\n`);
    } else {
      markdownLines.push(item);
    }
  }

  return markdownLines.join('\n').replace(/\n{3,}/g, '\n\n');
}

/**
 * Standalone PDF 1.4 Generator conforming to Adobe PDF Specification.
 * Produces valid, renderable multi-page vector PDF documents without external native dependencies.
 */
export function generateValidPDF(textContent: string): Buffer {
  const escapePdfText = (str: string): string => {
    return str
      .replace(/\\/g, '\\\\')
      .replace(/[(]/g, '\\(')
      .replace(/[)]/g, '\\)')
      .replace(/[^\x20-\x7E]/g, ' ');
  };

  const rawLines = (textContent || 'SuperDocs Exported Document').split('\n');
  const wrappedLines: string[] = [];

  for (const raw of rawLines) {
    if (raw.length > 85) {
      const words = raw.split(' ');
      let cur = '';
      for (const w of words) {
        if ((cur + ' ' + w).trim().length > 85) {
          wrappedLines.push(cur.trim());
          cur = w;
        } else {
          cur = cur ? `${cur} ${w}` : w;
        }
      }
      if (cur) wrappedLines.push(cur.trim());
    } else {
      wrappedLines.push(raw);
    }
  }

  const linesPerPage = 42;
  const pages: string[][] = [];
  for (let i = 0; i < wrappedLines.length; i += linesPerPage) {
    pages.push(wrappedLines.slice(i, i + linesPerPage));
  }
  if (pages.length === 0) pages.push(['SuperDocs Exported Document']);

  const N = pages.length;
  const catalogObjNum = 1;
  const pagesObjNum = 2;
  const firstPageObjNum = 3;
  const font1ObjNum = 3 + N;
  const font2ObjNum = 4 + N;
  const firstContentObjNum = 5 + N;
  const totalObjs = 4 + 2 * N;

  const header = '%PDF-1.4\n';
  const objects: Array<{ num: number; str: string }> = [];

  // 1: Catalog
  objects.push({ num: catalogObjNum, str: '1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n' });

  // 2: Pages
  const kids = Array.from({ length: N }, (_, i) => `${firstPageObjNum + i} 0 R`).join(' ');
  objects.push({ num: pagesObjNum, str: `2 0 obj\n<< /Type /Pages /Kids [${kids}] /Count ${N} >>\nendobj\n` });

  // 3 to 2+N: Page objects
  for (let i = 0; i < N; i++) {
    const pageNum = firstPageObjNum + i;
    const contentNum = firstContentObjNum + i;
    objects.push({
      num: pageNum,
      str: `${pageNum} 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 ${font1ObjNum} 0 R /F2 ${font2ObjNum} 0 R >> >> /Contents ${contentNum} 0 R >>\nendobj\n`
    });
  }

  // Fonts: Helvetica (regular) and Helvetica-Bold (bold)
  objects.push({ num: font1ObjNum, str: `${font1ObjNum} 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n` });
  objects.push({ num: font2ObjNum, str: `${font2ObjNum} 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>\nendobj\n` });

  // Content streams
  for (let i = 0; i < N; i++) {
    const contentNum = firstContentObjNum + i;
    const pageLines = pages[i];
    let streamBody = 'BT\n/F1 10 Tf\n14 TL\n50 790 Td\n';

    for (let j = 0; j < pageLines.length; j++) {
      const line = pageLines[j];
      const trimmed = line.trim();
      if (trimmed.startsWith('# ')) {
        const text = escapePdfText(trimmed.replace(/^#\s+/, ''));
        streamBody += `${j === 0 ? '' : 'T*\n'}/F2 14 Tf\n18 TL\n(${text}) Tj\n/F1 10 Tf\n14 TL\n`;
      } else if (trimmed.startsWith('## ') || trimmed.startsWith('### ')) {
        const text = escapePdfText(trimmed.replace(/^#+\s+/, ''));
        streamBody += `${j === 0 ? '' : 'T*\n'}/F2 11 Tf\n15 TL\n(${text}) Tj\n/F1 10 Tf\n14 TL\n`;
      } else {
        const text = escapePdfText(line);
        streamBody += `${j === 0 ? '' : 'T*\n'}(${text}) Tj\n`;
      }
    }
    streamBody += 'ET\n';

    const streamLen = Buffer.byteLength(streamBody, 'utf-8');
    objects.push({
      num: contentNum,
      str: `${contentNum} 0 obj\n<< /Length ${streamLen} >>\nstream\n${streamBody}endstream\nendobj\n`
    });
  }

  objects.sort((a, b) => a.num - b.num);

  let currentOffset = Buffer.byteLength(header, 'utf-8');
  const offsets: number[] = [0];

  let body = '';
  for (const obj of objects) {
    offsets[obj.num] = currentOffset;
    body += obj.str;
    currentOffset += Buffer.byteLength(obj.str, 'utf-8');
  }

  const startxref = currentOffset;
  const pad = (n: number) => n.toString().padStart(10, '0');

  let xref = `xref\n0 ${totalObjs + 1}\n0000000000 65535 f \n`;
  for (let i = 1; i <= totalObjs; i++) {
    xref += `${pad(offsets[i])} 00000 n \n`;
  }

  const trailer = `trailer\n<< /Size ${totalObjs + 1} /Root 1 0 R >>\nstartxref\n${startxref}\n%%EOF\n`;

  return Buffer.from(header + body + xref + trailer, 'utf-8');
}
