/** The Word boundary, and the only file that knows Office.js exists.
 *
 * Everything above this is testable; this file is not — Office.js needs a real
 * Word process. So the surface is tiny: four methods, each a thing only Word
 * does, with a `FakeHost` beside it so the pane's logic is covered by tests that
 * never open Word.
 *
 * See extensions/redaction-pane/README.md § "The API, and what it cannot do".
 */

export type Part =
  | "body"
  | "header"
  | "footer"
  | "footnote"
  | "endnote"
  | "comment"
  | "tracked_del";

export interface Redaction {
  /** Exactly the text to remove, as it appears in the document. */
  text: string;
  /** Where it lives. This routes the write, not just a label: a comment's text
   * is not in the body, so searching the body finds nothing. Each part is a
   * different Word object model. */
  part: Part;
  /** What replaces it — `[CREDIT CARD REDACTED]`, not `[REDACTED]`. Per item,
   * not per batch, because two items in one call rarely share a marker. */
  marker: string;
}

export interface AppliedResult {
  applied: number;
  /** What was actually done, when it was not "wrote the marker". The log
   * records this instead of inventing a marker that was never written. */
  detail?: string;
  /** Strings the host could not find or replace, with why. A redaction that
   * silently did nothing is the failure this tool exists to prevent, so the
   * adapter reports rather than swallows. */
  failed: { text: string; reason: string }[];
}

export interface Host {
  /** True inside Word. False everywhere else, which the pane says out loud. */
  readonly available: boolean;
  /** The open document as bytes — the whole package, not the body text, so
   * headers, comments and tracked changes come with it. */
  getFile(): Promise<{ filename: string; bytes: Uint8Array }>;
  /** Replace every occurrence of each string with its marker, in place. */
  redact(items: Redaction[]): Promise<AppliedResult>;
  /** Put the original text back where the marker is — the inverse of `redact`,
   * only called for a redaction the caller established is unambiguous (see
   * `revertBlocker` in App.tsx). */
  restore(item: Redaction): Promise<AppliedResult>;
  /** Fires when the document text changes, which is what re-arms the scan. */
  onDocumentChanged(handler: () => void): Promise<void>;
}

/** Whether this Word build has a requirement set. The manifest floor is WordApi
 * 1.3 — a higher one makes an older Word refuse to install — so anything above
 * (comments 1.4, footnotes 1.5, tracked changes 1.6) is checked at use, costing
 * one capability with a reason on the row, not the whole add-in.
 *
 * See extensions/redaction-pane/README.md § "Which Word APIs, and why not the newest".
 */
function supports(version: string): boolean {
  try {
    return Office.context.requirements.isSetSupported("WordApi", version);
  } catch {
    return false;
  }
}

/** The real one. Only ever constructed inside Word. */
class WordHost implements Host {
  readonly available = true;

  async getFile(): Promise<{ filename: string; bytes: Uint8Array }> {
    const file = await new Promise<Office.File>((resolve, reject) => {
      Office.context.document.getFileAsync(
        Office.FileType.Compressed,
        { sliceSize: 4 * 1024 * 1024 },
        (result) => {
          if (result.status === Office.AsyncResultStatus.Succeeded) resolve(result.value);
          else reject(new Error(result.error?.message ?? "getFileAsync failed"));
        },
      );
    });

    // Sliced: Word hands back a 4MB window at a time. Reassembled in order —
    // out of order produces a zip that opens and is subtly wrong.
    const chunks: Uint8Array[] = [];
    try {
      for (let index = 0; index < file.sliceCount; index += 1) {
        const slice = await new Promise<Office.Slice>((resolve, reject) => {
          file.getSliceAsync(index, (result) => {
            if (result.status === Office.AsyncResultStatus.Succeeded) resolve(result.value);
            else reject(new Error(result.error?.message ?? "getSliceAsync failed"));
          });
        });
        chunks.push(new Uint8Array(slice.data as number[]));
      }
    } finally {
      file.closeAsync();
    }

    const total = chunks.reduce((sum, part) => sum + part.length, 0);
    const bytes = new Uint8Array(total);
    let offset = 0;
    for (const part of chunks) {
      bytes.set(part, offset);
      offset += part.length;
    }
    return { filename: Office.context.document.url?.split("/").pop() ?? "document.docx", bytes };
  }

  async redact(items: Redaction[]): Promise<AppliedResult> {
    const result: AppliedResult = { applied: 0, failed: [] };

    await Word.run(async (context) => {
      const tracking = await this.#trackingMode(context);

      for (const item of items) {
        try {
          // A tracked deletion is resolved, not overwritten — safe whatever the
          // tracking mode, so it comes before the guard below.
          if (item.part === "tracked_del") {
            const accepted = await this.#acceptDeletion(context, item);
            if (accepted === 0) {
              result.failed.push({ text: item.text, reason: this.#nothingFound(item) });
              continue;
            }
            result.applied += accepted;
            result.detail = "removed by accepting the tracked deletion";
            continue;
          }

          // The bug this guard exists for: with Track Changes on, replacing a
          // span records the original as a tracked deletion, so the SSN stays in
          // the file — invisible, present in every export, while the pane says
          // "Redacted". Refusing is the only honest answer; turning tracking off
          // silently would change the reviewer's setting.
          if (tracking !== null && tracking !== Word.ChangeTrackingMode.off) {
            result.failed.push({
              text: item.text,
              reason:
                "Track Changes is on. Replacing this text would keep the original " +
                "in the file as a tracked deletion, so nothing was changed. Turn it " +
                "off (Review → Track Changes) and redact again.",
            });
            continue;
          }

          const applied =
            item.part === "comment"
              ? await this.#redactComment(context, item)
              : item.part === "footnote" || item.part === "endnote"
                ? await this.#redactNotes(context, item)
                : await this.#redactStories(context, item);

          if (applied === 0) {
            result.failed.push({ text: item.text, reason: this.#nothingFound(item) });
            continue;
          }
          result.applied += applied;
        } catch (error) {
          // One row failing must not abandon the batch, and the reason belongs
          // on the row, not a console nobody opens.
          result.failed.push({ text: item.text, reason: String((error as Error).message ?? error) });
        }
      }
      await context.sync();
    });

    return result;
  }

  /** The inverse of `redact`: find the marker, put the original text back.
   *
   * Not `Document.undo()`: that pops Word's undo stack, so a reviewer who
   * redacts, types a sentence, then reverts the redaction loses the sentence. A
   * stack is the wrong shape for "reverse this specific row". Correctness needs
   * the marker to be unambiguous, checked by the caller (`revertBlocker` in
   * App.tsx), not here.
   */
  async restore(item: Redaction): Promise<AppliedResult> {
    const result: AppliedResult = { applied: 0, failed: [] };
    const inverse: Redaction = { ...item, text: item.marker, marker: item.text };

    await Word.run(async (context) => {
      try {
        const tracking = await this.#trackingMode(context);
        if (tracking !== null && tracking !== Word.ChangeTrackingMode.off) {
          // As with redaction: putting the text back under tracking would leave
          // BOTH the marker and the restored text in the file.
          result.failed.push({
            text: item.text,
            reason: "Track Changes is on — turn it off (Review → Track Changes) and try again.",
          });
          return;
        }

        result.applied =
          item.part === "comment"
            ? await this.#redactComment(context, inverse)
            : item.part === "footnote" || item.part === "endnote"
              ? await this.#redactNotes(context, inverse)
              : await this.#redactStories(context, inverse);

        if (result.applied === 0) {
          result.failed.push({
            text: item.text,
            reason: `"${item.marker}" is no longer in the document — it may have been edited.`,
          });
        }
      } catch (error) {
        result.failed.push({ text: item.text, reason: String((error as Error).message ?? error) });
      }
      await context.sync();
    });

    return result;
  }

  /** `null` when this Word cannot be asked. WordApi 1.4. */
  async #trackingMode(context: Word.RequestContext): Promise<string | null> {
    if (!supports("1.4")) return null;
    const document = context.document;
    document.load("changeTrackingMode");
    await context.sync();
    return String(document.changeTrackingMode);
  }

  /** Tracked deletions — accepted, not overwritten. WordApi 1.6.
   *
   * Struck-through text has been told to go but hasn't; `search` doesn't match
   * it, so accepting the deletion is what takes it out of the file (`accept()`
   * removes, `reject()` would restore — easy to get backwards). Accepting
   * resolves the whole change, which can span more than the candidate — reported
   * on the row, not glossed, because it edits more than the one span clicked.
   */
  async #acceptDeletion(context: Word.RequestContext, item: Redaction): Promise<number> {
    if (!supports("1.6")) return 0;

    const changes = context.document.body.getTrackedChanges();
    changes.load("items/text,items/type");
    await context.sync();

    let accepted = 0;
    for (const change of changes.items) {
      if (change.type !== Word.TrackedChangeType.deleted) continue;
      if (!change.text.includes(item.text)) continue;
      change.accept();
      accepted += 1;
    }
    await context.sync();
    return accepted;
  }

  #nothingFound(item: Redaction): string {
    if (item.part === "tracked_del") {
      return supports("1.6")
        ? "no matching tracked deletion — it may have been accepted or rejected since the scan"
        : "this Word build cannot resolve tracked changes (needs WordApi 1.6). " +
          "Accept or reject the change in Word, or export a clean copy.";
    }
    if (item.part === "comment") {
      return supports("1.4")
        ? "not found in any comment — it may have been edited or deleted since the scan"
        : "this Word build cannot edit comments (needs WordApi 1.4)";
    }
    if (item.part === "footnote" || item.part === "endnote") {
      return supports("1.5")
        ? `not found in any ${item.part}`
        : `this Word build cannot edit ${item.part}s (needs WordApi 1.5)`;
    }
    return "not found in the open document";
  }

  /** Body, headers and footers — the stories `search` can walk. */
  async #redactStories(context: Word.RequestContext, item: Redaction): Promise<number> {
    // `search`, not a range walk: it finds the string wherever it is in the
    // story, including across formatting runs that split it mid-word.
    const ranges = context.document.body.search(item.text, { matchCase: true });
    ranges.load("items");
    await context.sync();

    const found = [...ranges.items, ...(await this.#sectionRanges(context, item.text))];
    // The marker replaces the span, never the sentence — layout and paragraph
    // structure are preserved.
    for (const range of found) range.insertText(item.marker, Word.InsertLocation.replace);
    return found.length;
  }

  /** Headers and footers are separate stories — `body.search` never sees them,
   * so a body-only pane reports clean while the letterhead still carries the
   * name. */
  async #sectionRanges(context: Word.RequestContext, text: string): Promise<Word.Range[]> {
    const sections = context.document.sections;
    sections.load("items");
    await context.sync();

    const found: Word.Range[] = [];
    for (const section of sections.items) {
      for (const kind of ["Primary", "FirstPage", "EvenPages"] as const) {
        for (const story of [section.getHeader(kind), section.getFooter(kind)]) {
          const hits = story.search(text, { matchCase: true });
          hits.load("items");
          await context.sync();
          found.push(...hits.items);
        }
      }
    }
    return found;
  }

  /** Comments — a different object model, and why this method exists. A comment's
   * text is not in the body, so `body.search` never sees it. Comments carry a
   * plain-string `content` (a string replace, not a range one), and replies are
   * separate objects walked too.
   */
  async #redactComment(context: Word.RequestContext, item: Redaction): Promise<number> {
    if (!supports("1.4")) return 0;

    const comments = context.document.body.getComments();
    comments.load("items/content");
    await context.sync();

    const replies = comments.items.map((comment) => comment.replies);
    for (const collection of replies) collection.load("items/content");
    await context.sync();

    let applied = 0;
    comments.items.forEach((comment, index) => {
      if (comment.content.includes(item.text)) {
        comment.content = comment.content.split(item.text).join(item.marker);
        applied += 1;
      }
      for (const reply of replies[index].items) {
        if (!reply.content.includes(item.text)) continue;
        reply.content = reply.content.split(item.text).join(item.marker);
        applied += 1;
      }
    });
    await context.sync();
    return applied;
  }

  /** Footnotes and endnotes — separate stories again, each with its own body. */
  async #redactNotes(context: Word.RequestContext, item: Redaction): Promise<number> {
    if (!supports("1.5")) return 0;

    const notes =
      item.part === "footnote" ? context.document.body.footnotes : context.document.body.endnotes;
    notes.load("items");
    await context.sync();

    const hits: Word.Range[] = [];
    for (const note of notes.items) {
      const found = note.body.search(item.text, { matchCase: true });
      found.load("items");
      await context.sync();
      hits.push(...found.items);
    }
    for (const range of hits) range.insertText(item.marker, Word.InsertLocation.replace);
    return hits.length;
  }

  async onDocumentChanged(handler: () => void): Promise<void> {
    // WordApi 1.6, not 1.5. Without the check these lines throw on an older
    // Word and the pane loses the events silently; absent, the reviewer
    // re-scans by hand.
    if (!supports("1.6")) return;

    // Re-arms the Scan button the moment somebody types — the pane never polls,
    // and never claims a scan is current when the document moved on beneath it.
    await Word.run(async (context) => {
      context.document.onParagraphChanged.add(async () => handler());
      context.document.onParagraphAdded.add(async () => handler());
      context.document.onParagraphDeleted.add(async () => handler());
      await context.sync();
    });
  }
}

/** For tests, and for the pane to render honestly outside Word — it shows what
 * it cannot do rather than pretending to work on a document that isn't there. */
export class FakeHost implements Host {
  readonly available = false;
  #text: string;

  constructor(text = "") {
    this.#text = text;
  }

  async getFile() {
    return { filename: "fake.docx", bytes: new TextEncoder().encode(this.#text) };
  }

  async redact(items: Redaction[]): Promise<AppliedResult> {
    let applied = 0;
    const failed: { text: string; reason: string }[] = [];
    for (const item of items) {
      if (item.part === "tracked_del") {
        failed.push({ text: item.text, reason: "inside a tracked deletion" });
        continue;
      }
      if (!this.#text.includes(item.text)) {
        failed.push({ text: item.text, reason: "not found in the open document" });
        continue;
      }
      this.#text = this.#text.split(item.text).join(item.marker);
      applied += 1;
    }
    return { applied, failed };
  }

  async restore(item: Redaction): Promise<AppliedResult> {
    if (!this.#text.includes(item.marker)) {
      return { applied: 0, failed: [{ text: item.text, reason: "marker not found" }] };
    }
    this.#text = this.#text.split(item.marker).join(item.text);
    return { applied: 1, failed: [] };
  }

  async onDocumentChanged(_handler: () => void) {
    // A no-op: nothing outside Word can fire Word's paragraph events, and the
    // behaviour they drive — "typing re-arms the scan" — is tested at the
    // reducer. A stored handler this fake could never call is not a test seam.
  }


  get text() {
    return this.#text;
  }
}

/** Which host this pane is running against, decided once at start-up. */
export async function detectHost(): Promise<Host> {
  if (typeof Office === "undefined" || !Office.onReady) return new FakeHost();
  const info = await Office.onReady();
  return info.host === Office.HostType.Word ? new WordHost() : new FakeHost();
}
