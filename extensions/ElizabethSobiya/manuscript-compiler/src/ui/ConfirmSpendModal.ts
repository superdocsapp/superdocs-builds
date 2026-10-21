/**
 * The no-spend preview.
 *
 * Every call that costs an operation goes through this dialog first, and the
 * dialog states three things the user cannot otherwise see: what will be sent,
 * how much of the book that is, and what it will cost. The free tier is 500
 * operations a month; a tool that spends them without saying so is a bad tool.
 */

import { App, Modal, Setting } from "obsidian";
import type { PassPlan } from "../superdocs/editorial";

export class ConfirmSpendModal extends Modal {
  private confirmed = false;
  private resolve: ((ok: boolean) => void) | null = null;

  constructor(
    app: App,
    private readonly title: string,
    private readonly plan: PassPlan,
    private readonly remaining: number | null,
  ) {
    super(app);
  }

  ask(): Promise<boolean> {
    return new Promise((resolve) => {
      this.resolve = resolve;
      this.open();
    });
  }

  override onOpen(): void {
    const { contentEl } = this;
    contentEl.addClass("mc-confirm");
    contentEl.createEl("h2", { text: this.title });

    const facts = contentEl.createEl("dl", { cls: "mc-confirm-facts" });
    const row = (term: string, value: string) => {
      facts.createEl("dt", { text: term });
      facts.createEl("dd", { text: value });
    };
    row("Cost", `${this.plan.estimatedOperations} SuperDocs operation${this.plan.estimatedOperations === 1 ? "" : "s"}`);
    row("Sends", this.plan.scopeDescription);
    row("Size", `${(this.plan.chars / 1000).toFixed(1)}k characters`);
    row(
      "Then",
      this.plan.writes
        ? "You review every proposed change before anything is written."
        : "A report only. Nothing in your vault is modified.",
    );
    if (this.remaining !== null) {
      row("Remaining after", `about ${Math.max(0, this.remaining - this.plan.estimatedOperations)} operations this month`);
    }

    const preview = contentEl.createEl("details", { cls: "mc-confirm-preview" });
    preview.createEl("summary", { text: "Show exactly what will be sent" });
    preview.createEl("pre", { text: this.plan.instruction });
    preview.createEl("pre", {
      text: this.plan.documentHtml.slice(0, 4000) + (this.plan.documentHtml.length > 4000 ? "\n…" : ""),
    });

    new Setting(contentEl)
      .addButton((b) => b.setButtonText("Cancel").onClick(() => this.close()))
      .addButton((b) =>
        b
          .setButtonText("Run it")
          .setCta()
          .onClick(() => {
            this.confirmed = true;
            this.close();
          }),
      );
  }

  override onClose(): void {
    this.contentEl.empty();
    this.resolve?.(this.confirmed);
    this.resolve = null;
  }
}
