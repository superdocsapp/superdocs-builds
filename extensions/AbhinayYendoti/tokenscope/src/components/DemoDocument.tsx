import { useMemo } from "react";
import { buildDocument, TARGET_PARAGRAPH, wordCount } from "../../shared/corpus.js";
import { PARAGRAPH_ATTRIBUTE } from "../host/demo.js";

/**
 * The demo document surface.
 *
 * This is the same generator the benchmark measures, at the same sizes, so a
 * reviewer without Word can reproduce the benchmark's central claim by hand:
 * switch the document from 3 pages to 300, run the same rewrite, and watch the
 * two numbers move apart.
 *
 * The surface is a real contenteditable region and the selection is read through
 * the browser's own Selection API. Nothing about the selection path is faked.
 */

export const DEMO_SIZES = [3, 10, 50] as const;

export type DemoSize = (typeof DEMO_SIZES)[number];

export function DemoDocument({
  pages,
  onPagesChange,
  surfaceRef
}: {
  pages: DemoSize;
  onPagesChange: (pages: DemoSize) => void;
  surfaceRef: React.RefObject<HTMLDivElement>;
}): JSX.Element {
  const document = useMemo(() => buildDocument(pages), [pages]);
  const words = useMemo(() => wordCount(document), [document]);

  return (
    <div className="demo">
      <header className="demo__header">
        <div>
          <h2>Demo document</h2>
          <p className="demo__meta">
            {pages} pages · {words.toLocaleString("en-US")} words · select any paragraph
          </p>
        </div>
        <div className="demo__sizes" role="group" aria-label="Document size">
          {DEMO_SIZES.map((size) => (
            <button
              key={size}
              type="button"
              className={`chip ${size === pages ? "chip--on" : ""}`}
              onClick={() => onPagesChange(size)}
            >
              {size} pages
            </button>
          ))}
        </div>
      </header>

      <p className="demo__hint">
        The verbose paragraph just past the middle is the one the benchmark rewrites.{" "}
        <button
          type="button"
          className="button button--link"
          onClick={() => selectTarget(surfaceRef.current)}
        >
          Select it
        </button>
      </p>

      <div
        className="demo__surface"
        ref={surfaceRef}
        contentEditable
        suppressContentEditableWarning
      >
        {document.paragraphs.map((paragraph) => {
          const isHeading = /^Section \d+\./u.test(paragraph.text) || paragraph.id === "p0";

          return isHeading ? (
            <h3 key={paragraph.id} {...{ [PARAGRAPH_ATTRIBUTE]: paragraph.id }}>
              {paragraph.text}
            </h3>
          ) : (
            <p key={paragraph.id} {...{ [PARAGRAPH_ATTRIBUTE]: paragraph.id }}>
              {paragraph.text}
            </p>
          );
        })}
      </div>
    </div>
  );
}

/** Put the browser's selection on the target paragraph, the way a drag would. */
function selectTarget(root: HTMLDivElement | null): void {
  if (root === null) return;

  const nodes = [...root.querySelectorAll<HTMLElement>(`[${PARAGRAPH_ATTRIBUTE}]`)];
  const target = nodes.find((node) => (node.textContent ?? "").trim() === TARGET_PARAGRAPH);

  if (target === undefined) return;

  const range = window.document.createRange();
  range.selectNodeContents(target);

  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
  target.scrollIntoView({ block: "center", behavior: "smooth" });
}
