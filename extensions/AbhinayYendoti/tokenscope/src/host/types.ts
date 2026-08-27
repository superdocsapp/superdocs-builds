import type { DocumentSnapshot } from "../../shared/types.js";

/**
 * The document host.
 *
 * TokenScope runs in two places: as a task pane inside Word, and as a standalone
 * page with its own document surface for anyone reviewing it without Word. Both
 * have to answer the same three questions, so both implement this interface and
 * nothing above it knows which one is loaded.
 */
export interface DocumentHost {
  readonly kind: "word" | "demo";
  /** Human-readable, shown in the pane header so the reader knows what they have. */
  readonly label: string;

  /** The document as paragraphs, in order. */
  readDocument(): Promise<DocumentSnapshot>;

  /** The text the user currently has selected. Empty string when nothing is. */
  readSelection(): Promise<string>;

  /** Call `listener` whenever the selection changes. Returns an unsubscribe. */
  onSelectionChange(listener: () => void): () => void;

  /**
   * Replace `oldText` with `newText` in the document.
   *
   * Called only after the user approves a specific change. Implementations must
   * fail rather than guess: if the original text is not found exactly once, the
   * document is not touched.
   */
  applyEdit(oldText: string, newText: string): Promise<void>;
}

export class HostError extends Error {
  override readonly name = "HostError";
}
