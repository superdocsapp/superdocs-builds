import type { DocumentSnapshot } from "../../shared/types.js";
import { HostError, type DocumentHost } from "./types.js";

/**
 * The Word host, over Office.js.
 *
 * Word owns the document; TokenScope only reads it and, once the user approves a
 * change, replaces one range. Paragraph identity is Word's own paragraph order,
 * which is stable for the lifetime of a pane session.
 */

declare const Office: typeof globalThis.Office | undefined;
declare const Word: typeof globalThis.Word | undefined;

export function officeIsAvailable(): boolean {
  return typeof Office !== "undefined" && Office?.context?.host === Office?.HostType?.Word;
}

/** Resolves once Office.js has finished initialising, or immediately if it has. */
export function whenOfficeReady(): Promise<boolean> {
  if (typeof Office === "undefined") return Promise.resolve(false);

  return Office.onReady()
    .then((info) => info.host === Office.HostType.Word)
    .catch(() => false);
}

export function createWordHost(): DocumentHost {
  if (typeof Word === "undefined") {
    throw new HostError("Office.js is not loaded, so the Word host cannot be created.");
  }

  return {
    kind: "word",
    label: "Microsoft Word",

    async readDocument(): Promise<DocumentSnapshot> {
      return Word.run(async (context) => {
        const paragraphs = context.document.body.paragraphs;
        paragraphs.load("items/text");
        await context.sync();

        return {
          paragraphs: paragraphs.items
            .map((item, index) => ({ id: `w${index}`, text: item.text }))
            .filter((p) => p.text.trim().length > 0)
        };
      });
    },

    async readSelection(): Promise<string> {
      return Word.run(async (context) => {
        const range = context.document.getSelection();
        range.load("text");
        await context.sync();
        return range.text ?? "";
      });
    },

    onSelectionChange(listener: () => void): () => void {
      if (typeof Office === "undefined") return () => {};

      const handler = () => listener();

      void Office.context.document.addHandlerAsync(
        Office.EventType.DocumentSelectionChanged,
        handler
      );

      return () => {
        void Office.context.document.removeHandlerAsync(Office.EventType.DocumentSelectionChanged, {
          handler
        });
      };
    },

    /**
     * Replace the approved text.
     *
     * Word's search is the authority on where the text is. Zero hits means the
     * document moved under us; more than one means the target is ambiguous.
     * Neither is a case where guessing is better than stopping.
     */
    async applyEdit(oldText: string, newText: string): Promise<void> {
      return Word.run(async (context) => {
        // Word's search string has a 255-character ceiling; anchor on the head of
        // the paragraph and replace the whole matched paragraph.
        const needle = oldText.trim().slice(0, 250);
        const results = context.document.body.search(needle, { matchCase: true });
        results.load("items");
        await context.sync();

        if (results.items.length === 0) {
          throw new HostError(
            "The original text is no longer in the document, so nothing was changed."
          );
        }

        if (results.items.length > 1) {
          throw new HostError(
            `The original text appears ${results.items.length} times, so TokenScope will not ` +
              "guess which one you meant. Nothing was changed."
          );
        }

        const match = results.items[0];

        if (match === undefined) {
          throw new HostError("Word returned no usable range. Nothing was changed.");
        }

        const paragraph = match.paragraphs.getFirst();
        paragraph.insertText(newText, Word.InsertLocation.replace);
        await context.sync();
      });
    }
  };
}
