/**
 * The human gate.
 *
 * One card per proposed change, each with its own Accept and Reject. Rejecting one
 * change does not touch the others; the modal collects a decision per change and
 * sends them together. Closing without deciding rejects nothing and accepts
 * nothing — the job stays pending and is offered again next time.
 *
 * The diff is word-level and computed locally. It is shown as before/after because
 * an editor's instinct is to read the sentence, not the token stream.
 */

import { App, Modal, Setting } from "obsidian";
import type { ProposedChange } from "../superdocs/client";
import { toText, wordDiff } from "../core/diff";

export interface ReviewDecision {
  changeId: string;
  approved: boolean;
  feedback?: string;
}

export interface ReviewResult {
  decisions: ReviewDecision[];
  /** True when the user closed the dialog without submitting. */
  deferred: boolean;
}

export class ReviewModal extends Modal {
  private readonly decisions = new Map<string, boolean>();
  private readonly feedback = new Map<string, string>();
  private submitted = false;
  private resolve: ((r: ReviewResult) => void) | null = null;

  constructor(
    app: App,
    private readonly instruction: string,
    private readonly changes: ProposedChange[],
  ) {
    super(app);
  }

  waitForDecision(): Promise<ReviewResult> {
    return new Promise((resolve) => {
      this.resolve = resolve;
      this.open();
    });
  }

  override onOpen(): void {
    const { contentEl } = this;
    contentEl.addClass("mc-review");
    contentEl.createEl("h2", { text: "Review proposed changes" });
    contentEl.createEl("p", {
      cls: "mc-review-instruction",
      text: `You asked for: ${this.instruction}`,
    });
    contentEl.createEl("p", {
      cls: "mc-review-note",
      text: `${this.changes.length} change${
        this.changes.length === 1 ? "" : "s"
      } proposed. Nothing is written to your vault until you decide. Undecided changes stay pending.`,
    });

    const list = contentEl.createDiv({ cls: "mc-review-list" });
    this.changes.forEach((change, index) => this.renderCard(list, change, index));

    const footer = contentEl.createDiv({ cls: "mc-review-footer" });
    new Setting(footer)
      .addButton((b) =>
        b.setButtonText("Accept all").onClick(() => {
          for (const c of this.changes) this.decisions.set(c.change_id, true);
          this.refreshCards();
        }),
      )
      .addButton((b) =>
        b.setButtonText("Reject all").onClick(() => {
          for (const c of this.changes) this.decisions.set(c.change_id, false);
          this.refreshCards();
        }),
      )
      .addButton((b) =>
        b
          .setButtonText("Apply decisions")
          .setCta()
          .onClick(() => {
            this.submitted = true;
            this.close();
          }),
      );

    this.refreshCards();
  }

  private cardEls: Array<{ el: HTMLElement; change: ProposedChange }> = [];

  private renderCard(parent: HTMLElement, change: ProposedChange, index: number): void {
    const card = parent.createDiv({ cls: "mc-change-card" });
    this.cardEls.push({ el: card, change });

    const head = card.createDiv({ cls: "mc-change-head" });
    head.createSpan({ cls: `mc-op mc-op-${change.operation}`, text: change.operation });
    head.createSpan({ cls: "mc-change-index", text: `${index + 1} of ${this.changes.length}` });

    if (change.ai_explanation) {
      card.createEl("p", { cls: "mc-change-why", text: change.ai_explanation });
    }

    const body = card.createDiv({ cls: "mc-change-body" });
    if (change.operation === "delete") {
      body.createDiv({ cls: "mc-diff-removed" }).setText(toText(change.old_html ?? ""));
    } else if (change.operation === "create") {
      body.createDiv({ cls: "mc-diff-added" }).setText(toText(change.new_html ?? ""));
    } else {
      const diff = wordDiff(toText(change.old_html ?? ""), toText(change.new_html ?? ""));
      const pane = body.createDiv({ cls: "mc-diff" });
      for (const part of diff) {
        const span = pane.createSpan({ text: part.text });
        if (part.kind === "add") span.addClass("mc-diff-add");
        if (part.kind === "del") span.addClass("mc-diff-del");
      }
    }

    const controls = card.createDiv({ cls: "mc-change-controls" });
    const accept = controls.createEl("button", { text: "Accept" });
    const reject = controls.createEl("button", { text: "Reject" });
    accept.addEventListener("click", () => {
      this.decisions.set(change.change_id, true);
      this.refreshCards();
    });
    reject.addEventListener("click", () => {
      this.decisions.set(change.change_id, false);
      this.refreshCards();
      const note = card.querySelector<HTMLInputElement>(".mc-feedback-input");
      note?.focus();
    });

    const feedbackWrap = controls.createDiv({ cls: "mc-feedback" });
    const input = feedbackWrap.createEl("input", {
      cls: "mc-feedback-input",
      attr: { type: "text", placeholder: "Why? (optional — sent back so it can try again)" },
    });
    input.addEventListener("input", () => this.feedback.set(change.change_id, input.value));

    card.dataset.changeId = change.change_id;
  }

  private refreshCards(): void {
    for (const { el, change } of this.cardEls) {
      const decision = this.decisions.get(change.change_id);
      el.toggleClass("mc-accepted", decision === true);
      el.toggleClass("mc-rejected", decision === false);
      el.toggleClass("mc-undecided", decision === undefined);
    }
  }

  override onClose(): void {
    this.contentEl.empty();
    const decisions: ReviewDecision[] = [];
    if (this.submitted) {
      for (const change of this.changes) {
        const approved = this.decisions.get(change.change_id);
        if (approved === undefined) continue; // undecided is not a decision
        const note = this.feedback.get(change.change_id);
        decisions.push({
          changeId: change.change_id,
          approved,
          ...(note && !approved ? { feedback: note } : {}),
        });
      }
    }
    this.resolve?.({ decisions, deferred: !this.submitted });
    this.resolve = null;
  }
}
