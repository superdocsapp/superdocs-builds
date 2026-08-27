import type { DocumentSnapshot } from "../../shared/types.js";
import { HostError, type DocumentHost } from "./types.js";

/**
 * The demo host: a real document surface in the page, for reviewing TokenScope
 * without Word.
 *
 * It is not a simulation of Word. It is a live contenteditable region, read
 * through the browser's own Selection API, so the selection path exercised here
 * is a real one - the same code above it, the same API calls beneath it. Only
 * the editor differs.
 */

const PARAGRAPH_ATTRIBUTE = "data-paragraph-id";

export function createDemoHost(root: HTMLElement): DocumentHost {
  return {
    kind: "demo",
    label: "TokenScope demo document",

    async readDocument(): Promise<DocumentSnapshot> {
      const nodes = root.querySelectorAll<HTMLElement>(`[${PARAGRAPH_ATTRIBUTE}]`);

      return {
        paragraphs: [...nodes]
          .map((node) => ({
            id: node.getAttribute(PARAGRAPH_ATTRIBUTE) ?? "",
            text: node.textContent ?? ""
          }))
          .filter((p) => p.id.length > 0 && p.text.trim().length > 0)
      };
    },

    async readSelection(): Promise<string> {
      const selection = window.getSelection();

      if (selection === null || selection.isCollapsed || selection.rangeCount === 0) return "";

      const range = selection.getRangeAt(0);

      // Ignore selections made outside the document surface: selecting the pane's
      // own result text is not selecting the document.
      if (!root.contains(range.commonAncestorContainer)) return "";

      return selection.toString();
    },

    onSelectionChange(listener: () => void): () => void {
      const handler = () => listener();
      document.addEventListener("selectionchange", handler);
      return () => document.removeEventListener("selectionchange", handler);
    },

    async applyEdit(oldText: string, newText: string): Promise<void> {
      const nodes = [...root.querySelectorAll<HTMLElement>(`[${PARAGRAPH_ATTRIBUTE}]`)];
      const normalized = normalize(oldText);
      const matches = nodes.filter((node) => normalize(node.textContent ?? "") === normalized);

      if (matches.length === 0) {
        throw new HostError(
          "The original text is no longer in the document, so nothing was changed."
        );
      }

      if (matches.length > 1) {
        throw new HostError(
          `The original text appears ${matches.length} times, so TokenScope will not guess ` +
            "which one you meant. Nothing was changed."
        );
      }

      const target = matches[0];

      if (target === undefined) throw new HostError("No usable paragraph. Nothing was changed.");

      target.textContent = newText;
      target.dataset["applied"] = "true";
    }
  };
}

function normalize(text: string): string {
  return text.replace(/\s+/gu, " ").trim();
}

export { PARAGRAPH_ATTRIBUTE };
