import { App, Modal, Notice, PluginSettingTab, Setting } from "obsidian";
import { htmlToMarkdown } from "./ownership";
import type { LivingNoteSettings, PendingChange, PreviewPlan } from "./types";

export interface ReviewDecision {
  change_id: string;
  approved: boolean;
  feedback?: string;
}

export class ReviewModal extends Modal {
  private readonly changes: PendingChange[];
  private readonly round: number;
  private readonly maxRounds: number;
  private readonly resolveDecision: (decisions: ReviewDecision[]) => void;
  private settled = false;
  private readonly approved = new Set<string>();
  private readonly feedback = new Map<string, string>();

  constructor(app: App, changes: PendingChange[], round: number, maxRounds: number, resolveDecision: (decisions: ReviewDecision[]) => void) {
    super(app);
    this.changes = changes;
    this.round = round;
    this.maxRounds = maxRounds;
    this.resolveDecision = resolveDecision;
  }

  override onOpen(): void {
    this.modalEl.addClass("superdocs-review-modal");
    this.titleEl.setText(`Review SuperDocs changes (round ${this.round} of ${this.maxRounds})`);
    this.contentEl.createEl("p", {
      cls: "superdocs-review-note",
      text: "Nothing is written to the vault until you decide. Approved changes are checked again against the owned regions before anything lands in the note.",
    });

    const list = this.contentEl.createDiv({ cls: "superdocs-review-list" });
    for (const change of this.changes) {
      const row = list.createDiv({ cls: "superdocs-review-row" });
      const header = row.createDiv({ cls: "superdocs-review-header" });
      const label = header.createEl("label", { cls: "superdocs-review-toggle" });
      const checkbox = label.createEl("input", { attr: { type: "checkbox" } });
      label.createSpan({ text: ` Approve this ${change.operation}` });
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) this.approved.add(change.change_id);
        else this.approved.delete(change.change_id);
        row.toggleClass("is-approved", checkbox.checked);
      });

      row.createEl("p", { cls: "superdocs-review-reason", text: change.ai_explanation || "SuperDocs proposed a targeted change." });
      const diff = row.createDiv({ cls: "superdocs-review-diff" });
      this.side(diff, "Now", change.old_html, "(new content)");
      this.side(diff, "Proposed", change.new_html, "(removed)");

      const feedback = row.createEl("input", {
        cls: "superdocs-review-feedback",
        attr: { type: "text", placeholder: "Optional feedback, sent only if you reject this change" },
      });
      feedback.addEventListener("input", () => this.feedback.set(change.change_id, feedback.value.trim()));
    }

    const buttons = this.contentEl.createDiv({ cls: "modal-button-container" });
    const approve = buttons.createEl("button", { text: "Apply selected", cls: "mod-cta" });
    approve.addEventListener("click", () => this.finish(false));
    const rejectAll = buttons.createEl("button", { text: "Reject all", cls: "mod-warning" });
    rejectAll.addEventListener("click", () => this.finish(true));
  }

  private side(parent: HTMLElement, title: string, html: string | null | undefined, empty: string): void {
    const column = parent.createDiv({ cls: `superdocs-review-side superdocs-review-${title.toLowerCase()}` });
    column.createEl("strong", { text: title });
    column.createEl("pre", { text: html ? htmlToMarkdown(html) : empty });
  }

  override onClose(): void {
    this.settle(this.changes.map((change) => ({
      change_id: change.change_id,
      approved: false,
      feedback: "The review window was closed without a decision; do not apply this change.",
    })));
    this.contentEl.empty();
  }

  private finish(rejectAll: boolean): void {
    this.settle(this.changes.map((change) => {
      const approved = !rejectAll && this.approved.has(change.change_id);
      const note = this.feedback.get(change.change_id);
      return {
        change_id: change.change_id,
        approved,
        ...(approved ? {} : { feedback: note || "The reviewer rejected this proposed change." }),
      };
    }));
    this.close();
  }

  private settle(decisions: ReviewDecision[]): void {
    if (this.settled) return;
    this.settled = true;
    this.resolveDecision(decisions);
  }
}

export function reviewChanges(app: App, changes: PendingChange[], round: number, maxRounds: number): Promise<ReviewDecision[]> {
  return new Promise((resolve) => new ReviewModal(app, changes, round, maxRounds, resolve).open());
}

export class PreviewModal extends Modal {
  private readonly plan: PreviewPlan;
  constructor(app: App, plan: PreviewPlan) {
    super(app);
    this.plan = plan;
  }

  override onOpen(): void {
    this.modalEl.addClass("superdocs-review-modal");
    this.titleEl.setText("Living-note preview (no spend)");
    this.contentEl.createEl("p", { cls: "superdocs-review-note", text: "This preview made no SuperDocs call and spent zero operations." });

    const facts = this.contentEl.createEl("ul");
    facts.createEl("li", { text: `Designated note: ${this.plan.targetPath}` });
    facts.createEl("li", { text: `Owned regions: ${this.plan.regions.join(", ")}` });
    facts.createEl("li", { text: `Source fingerprint: ${this.plan.sourceFingerprint.hash} over ${this.plan.sourceFingerprint.files.length} note(s)` });

    this.contentEl.createEl("h4", { text: "Sources a run would attach, most relevant first" });
    const list = this.contentEl.createEl("ol");
    if (this.plan.sources.length === 0) list.createEl("li", { text: "no eligible source notes found" });
    for (const source of this.plan.sources) list.createEl("li", { text: `${source.path} (relevance ${source.score})` });

    this.contentEl.createEl("h4", { text: "The only text a run would upload as editable" });
    this.contentEl.createEl("pre", { cls: "superdocs-preview-doc", text: this.plan.regionDocument });

    const buttons = this.contentEl.createDiv({ cls: "modal-button-container" });
    const close = buttons.createEl("button", { text: "Close", cls: "mod-cta" });
    close.addEventListener("click", () => this.close());
  }

  override onClose(): void {
    this.contentEl.empty();
  }
}

export class LivingNoteSettingTab extends PluginSettingTab {
  private readonly settings: LivingNoteSettings;
  private readonly save: () => Promise<void>;

  constructor(app: App, plugin: { settings: LivingNoteSettings; saveSettings: () => Promise<void> }) {
    super(app, plugin as never);
    this.settings = plugin.settings;
    // Called through the plugin, not detached from it: an unbound reference
    // would throw on every keystroke and silently persist nothing.
    this.save = async () => {
      try {
        await plugin.saveSettings();
      } catch (error) {
        showError(error);
      }
    };
  }

  override display(): void {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl("p", { text: "The plugin writes only between explicit superdocs:owned markers. Everything else in the note is left alone." });

    new Setting(containerEl).setName("Connection").setHeading();
    new Setting(containerEl).setName("SuperDocs API key").setDesc("Stored in this vault's local plugin data. Never logged, never committed.")
      .addText((text) => {
        text.inputEl.type = "password";
        text.setPlaceholder("sk_...").setValue(this.settings.apiKey).onChange(async (value) => { this.settings.apiKey = value.trim(); await this.save(); });
      });
    new Setting(containerEl).setName("API base URL")
      .addText((text) => text.setValue(this.settings.baseUrl).onChange(async (value) => { this.settings.baseUrl = value.trim() || "https://api.superdocs.app"; await this.save(); }));

    new Setting(containerEl).setName("Scope").setHeading();
    new Setting(containerEl).setName("Designated note").setDesc("Vault-relative path, for example SuperDocs Demo/Living Note.md.")
      .addText((text) => text.setValue(this.settings.targetPath).onChange(async (value) => { this.settings.targetPath = value.trim(); await this.save(); }));
    new Setting(containerEl).setName("Source folders").setDesc("Comma-separated folders. Leave blank to use every Markdown note except the designated one.")
      .addText((text) => text.setValue(this.settings.sourceFolders.join(", ")).onChange(async (value) => { this.settings.sourceFolders = splitList(value); await this.save(); }));
    new Setting(containerEl).setName("Maximum source notes").setDesc("How many notes a run may attach. Each attachment is uploaded to SuperDocs.")
      .addSlider((slider) => slider.setLimits(1, 20, 1).setValue(this.settings.maxSources).setDynamicTooltip().onChange(async (value) => { this.settings.maxSources = value; await this.save(); }));

    new Setting(containerEl).setName("Running").setHeading();
    new Setting(containerEl).setName("Preview only").setDesc("Force every run into no-spend preview mode, even the sync command.")
      .addToggle((toggle) => toggle.setValue(this.settings.previewOnly).onChange(async (value) => { this.settings.previewOnly = value; await this.save(); }));
    new Setting(containerEl).setName("Automatic sync").setDesc("Runs only after an eligible source note changes. The designated note never triggers a run.")
      .addToggle((toggle) => toggle.setValue(this.settings.autoSync).onChange(async (value) => { this.settings.autoSync = value; await this.save(); }));
    new Setting(containerEl).setName("Scheduled check (minutes)").setDesc("How often automatic sync may look for a new source fingerprint.")
      .addText((text) => text.setValue(String(this.settings.refreshIntervalMinutes)).onChange(async (value) => {
        const minutes = Number(value);
        if (Number.isFinite(minutes) && minutes >= 1) this.settings.refreshIntervalMinutes = Math.floor(minutes);
        await this.save();
      }));

    new Setting(containerEl).setName("SuperDocs features").setHeading();
    new Setting(containerEl).setName("Cross-session search").setDesc("Let SuperDocs search prior documents and chats owned by this API key.")
      .addToggle((toggle) => toggle.setValue(this.settings.enableCrossSessionSearch).onChange(async (value) => { this.settings.enableCrossSessionSearch = value; await this.save(); }));
    new Setting(containerEl).setName("Cross-session memory").setDesc("Keep an owner-scoped memory of accepted preferences between runs.")
      .addToggle((toggle) => toggle.setValue(this.settings.enableCrossSessionMemory).onChange(async (value) => { this.settings.enableCrossSessionMemory = value; await this.save(); }));
    new Setting(containerEl).setName("Memory key").setDesc("Optional. Use a stable key if one API key serves more than one vault.")
      .addText((text) => text.setValue(this.settings.memoryKey).onChange(async (value) => { this.settings.memoryKey = value.trim(); await this.save(); }));
    new Setting(containerEl).setName("Model tier")
      .addDropdown((dropdown) => dropdown.addOptions({ core: "Core", turbo: "Turbo", pro: "Pro", max: "Max" }).setValue(this.settings.modelTier).onChange(async (value) => { this.settings.modelTier = value as LivingNoteSettings["modelTier"]; await this.save(); }));
    new Setting(containerEl).setName("Thinking depth")
      .addDropdown((dropdown) => dropdown.addOptions({ fast: "Fast", balanced: "Balanced", deep: "Deep" }).setValue(this.settings.thinkingDepth).onChange(async (value) => { this.settings.thinkingDepth = value as LivingNoteSettings["thinkingDepth"]; await this.save(); }));
  }
}

function splitList(value: string): string[] {
  return [...new Set(value.split(",").map((item) => item.trim()).filter(Boolean))];
}

export function showError(error: unknown): void {
  const message = error instanceof Error ? error.message : "The living-note run failed for an unknown reason.";
  new Notice(`SuperDocs Living Note: ${message}`, 12_000);
}
