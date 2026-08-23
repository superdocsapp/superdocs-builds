import { useCallback, useEffect, useRef, useState } from "react";
import {
  type Cut,
  type PageSetup,
  type Snap,
  applySnap,
  hasWordAt,
  pageBox,
  pageOf,
  partAfter,
  quoteAround,
} from "./split";

/** The document, rendered at real page size, with the cuts drawn on it.
 *
 * The API carries no page or line numbers, so this paginates: it measures every
 * line with `Range.getClientRects()` and numbers them. That approximates Word's
 * pagination and does not need to match it — the reviewer points at content, so
 * a click on "Warranties" cuts at that word whatever page Word later puts it on.
 *
 * See use-cases/doc-splitter/README.md § "Page and line numbers are ours, not Word's".
 */
export function Preview({
  html,
  pageSetup,
  cuts,
  snap,
  onCut,
  onRemove,
}: {
  html: string;
  pageSetup: PageSetup | null;
  cuts: Cut[];
  snap: Snap;
  onCut: (cut: Cut) => void;
  onRemove: (index: number) => void;
}) {
  const paper = useRef<HTMLDivElement>(null);
  const [lines, setLines] = useState<LineBox[]>([]);
  const box = pageBox(pageSetup);

  // Re-measure on render and box change. Fonts load async, so one pass on mount
  // measures the fallback face and every line number comes out wrong.
  useEffect(() => {
    if (!paper.current) return;
    let alive = true;
    const measure = () => alive && setLines(measureLines(paper.current!));
    measure();
    void document.fonts?.ready.then(measure);
    const observer = new ResizeObserver(measure);
    observer.observe(paper.current);
    return () => {
      alive = false;
      observer.disconnect();
    };
  }, [html, box.width]);

  const place = useCallback(
    (event: React.MouseEvent) => {
      const found = caretAt(event.clientX, event.clientY, paper.current);
      if (!found) return;
      // A click in the gap resolves to the end of the paragraph above — no word
      // there, so no split point.
      if (!hasWordAt(found.blockText, found.offset)) return;

      const offset = applySnap(found.blockText, found.offset, snap);
      const line = lines.find(
        (candidate) =>
          found.top >= candidate.top - 1 && found.top <= candidate.top + candidate.height + 1,
      );
      onCut({
        chunk_id: found.chunkId,
        offset,
        page: pageOf(found.top, box.height),
        line: line ? line.number : 0,
        quote: quoteAround(found.blockText, offset),
      });
    },
    [lines, box.height, snap, onCut],
  );

  const pages = Math.max(1, Math.ceil((paper.current?.scrollHeight ?? 0) / box.height));

  return (
    <div className="preview">
      <div className="preview__rail" aria-hidden>
        {lines.map((line) => (
          <span key={line.number} className="rail__line" style={{ top: line.top }}>
            {line.number}
          </span>
        ))}
      </div>

      <div className="preview__paper" style={{ width: box.width }}>
        {/* Page rules, drawn where our pagination says a page ends. */}
        {Array.from({ length: pages - 1 }, (_, index) => (
          <div key={index} className="preview__pagebreak" style={{ top: (index + 1) * box.height }}>
            <span>page {index + 2}</span>
          </div>
        ))}

        {/* `dangerouslySetInnerHTML` is the point: this is the reviewer's own
            document from our own service, and rendering it as text would defeat
            the preview. It is never re-sent — the split uses the service's copy. */}
        <div
          ref={paper}
          className="preview__doc"
          onClick={place}
          dangerouslySetInnerHTML={{ __html: html }}
        />

        {cuts.map((cut, index) => (
          <Marker key={`${cut.chunk_id}:${cut.offset}`} cut={cut} index={index} onRemove={onRemove} />
        ))}
      </div>
    </div>
  );
}

/** Where a part begins, drawn at the character. A caret sits on the exact
 * character and a rule runs from there to the end of the line — the shape of
 * what the next part takes. A block-wide rule showed only which line. */
function Marker({
  cut,
  index,
  onRemove,
}: {
  cut: Cut;
  index: number;
  onRemove: (index: number) => void;
}) {
  const [at, setAt] = useState<{ top: number; left: number; height: number } | null>(null);

  // Measured from the live DOM, not stored: the text it sits on moves on resize.
  useEffect(() => {
    const update = () => setAt(caretBox(cut));
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, [cut]);

  if (!at) return null;
  return (
    <div className="marker" style={{ top: at.top, height: at.height }}>
      <span className="marker__caret" style={{ left: at.left }} />
      <span className="marker__rule" style={{ left: at.left }} />
      <span className="marker__tag">
        part {partAfter(index)} starts · p{cut.page} L{cut.line}
      </span>
      <button className="marker__remove" onClick={() => onRemove(index)} aria-label="Remove">
        ×
      </button>
    </div>
  );
}

interface LineBox {
  number: number;
  top: number;
  height: number;
}

/** Every line box in the document, in order. `getClientRects()` over a text-node
 * Range returns one rect per rendered line — the only way to see the breaks,
 * since there is no "line" in the DOM to count. */
function measureLines(root: HTMLElement): LineBox[] {
  const origin = root.getBoundingClientRect().top;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const tops: LineBox[] = [];
  const range = document.createRange();

  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (!node.textContent?.trim()) continue;
    range.selectNodeContents(node);
    for (const rect of Array.from(range.getClientRects())) {
      if (rect.height === 0) continue;
      const top = Math.round(rect.top - origin);
      // One entry per line, not per text node: a line containing bold text is
      // three nodes and one line.
      if (!tops.some((seen) => Math.abs(seen.top - top) < 3)) {
        tops.push({ number: 0, top, height: rect.height });
      }
    }
  }
  return tops
    .sort((left, right) => left.top - right.top)
    .map((line, index) => ({ ...line, number: index + 1 }));
}

/** A click → the block it landed in and the character offset within it. */
function caretAt(x: number, y: number, root: HTMLElement | null) {
  if (!root) return null;
  const caret = caretFromPoint(x, y);
  if (!caret) return null;

  const block = (caret.node.parentElement as HTMLElement | null)?.closest("[data-chunk-id]");
  if (!block || !root.contains(block)) return null;

  // Sum text nodes before the caret within this block — the same count the
  // Python side cuts at, so the two never disagree.
  const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT);
  let offset = 0;
  let blockText = "";
  let reached = false;
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (node === caret.node) {
      offset = blockText.length + caret.offset;
      reached = true;
    }
    blockText += node.textContent ?? "";
  }
  if (!reached) return null;

  const rect = rectFor(caret.node, caret.offset);
  return {
    chunkId: block.getAttribute("data-chunk-id") ?? "",
    offset,
    blockText,
    top: Math.round((rect?.top ?? 0) - root.getBoundingClientRect().top),
  };
}

/** Two browsers, two spellings of the same API. */
function caretFromPoint(x: number, y: number): { node: Node; offset: number } | null {
  const legacy = (document as Document & {
    caretRangeFromPoint?: (x: number, y: number) => Range | null;
  }).caretRangeFromPoint;
  if (legacy) {
    const range = legacy.call(document, x, y);
    return range ? { node: range.startContainer, offset: range.startOffset } : null;
  }
  const modern = (document as Document & {
    caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null;
  }).caretPositionFromPoint;
  const position = modern?.call(document, x, y);
  return position ? { node: position.offsetNode, offset: position.offset } : null;
}

function rectFor(node: Node, offset: number): DOMRect | null {
  const range = document.createRange();
  try {
    range.setStart(node, offset);
    range.setEnd(node, offset);
  } catch {
    return null;
  }
  return range.getClientRects()[0] ?? range.getBoundingClientRect();
}

/** Where a stored cut sits on screen right now — the exact character box. */
function caretBox(cut: Cut): { top: number; left: number; height: number } | null {
  const block = document.querySelector(`[data-chunk-id="${CSS.escape(cut.chunk_id)}"]`);
  const paper = document.querySelector(".preview__doc");
  if (!block || !paper) return null;

  const origin = paper.getBoundingClientRect();
  const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT);
  let seen = 0;
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const length = node.textContent?.length ?? 0;
    if (seen + length >= cut.offset) {
      const rect = rectFor(node, cut.offset - seen);
      if (rect && rect.height) {
        return {
          top: Math.round(rect.top - origin.top),
          left: Math.round(rect.left - origin.left),
          height: Math.round(rect.height),
        };
      }
      break;
    }
    seen += length;
  }
  const fallback = block.getBoundingClientRect();
  return {
    top: Math.round(fallback.top - origin.top),
    left: 0,
    height: Math.round(parseFloat(getComputedStyle(block).lineHeight) || 20),
  };
}
