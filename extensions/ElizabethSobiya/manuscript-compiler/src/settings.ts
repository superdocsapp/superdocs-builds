import { App, PluginSettingTab, Setting, Notice } from "obsidian";
import type ManuscriptCompilerPlugin from "./main";
import { DEFAULT_COMPILE_OPTIONS, type CompileOptions } from "./core/types";
import type { PendingJob } from "./superdocs/jobs";

export interface ManuscriptSettings extends CompileOptions {
  apiKey: string;
  apiBase: string;
  /** Vault folder the compiled files are written into. */
  outputFolder: string;
  paperSize: "Letter" | "A4" | "A3" | "Legal";
  margins: "narrow" | "normal" | "wide";
  /** Ask for confirmation before any operation that costs money. */
  confirmSpend: boolean;
  /** Recompile automatically when a chapter on the spine is saved. */
  compileOnSave: boolean;
  /** A job that was awaiting review when Obsidian last closed. */
  pendingJob: PendingJob | null;
  /** Running total of operations this plugin has spent, for the status bar. */
  operationsSpent: number;
  lastKnownRemaining: number | null;
}

export const DEFAULT_SETTINGS: ManuscriptSettings = {
  ...DEFAULT_COMPILE_OPTIONS,
  apiKey: "",
  apiBase: "https://api.superdocs.app",
  outputFolder: "Manuscript Output",
  paperSize: "A4",
  margins: "normal",
  confirmSpend: true,
  compileOnSave: false,
  pendingJob: null,
  operationsSpent: 0,
  lastKnownRemaining: null,
};

export class ManuscriptSettingTab extends PluginSettingTab {
  constructor(
    app: App,
    private readonly plugin: ManuscriptCompilerPlugin,
  ) {
    super(app, plugin);
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();

    // --- The manuscript ------------------------------------------------------
    new Setting(containerEl).setName("Manuscript").setHeading();

    new Setting(containerEl)
      .setName("Spine note")
      .setDesc(
        "The index note that lists your chapters as [[wikilinks]], in order. Everything else — parts, front matter, back matter — is read from that one note.",
      )
      .addText((text) =>
        text
          .setPlaceholder("Manuscript.md")
          .setValue(this.plugin.settings.spinePath)
          .onChange(async (value) => {
            this.plugin.settings.spinePath = value.trim() || "Manuscript.md";
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Bibliography")
      .setDesc(
        "A BibTeX .bib file in the vault. Leave empty to disable citations. A `bibliography:` key in the spine's frontmatter overrides this.",
      )
      .addText((text) =>
        text
          .setPlaceholder("References/library.bib")
          .setValue(this.plugin.settings.bibliographyPath ?? "")
          .onChange(async (value) => {
            this.plugin.settings.bibliographyPath = value.trim() || null;
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Output folder")
      .setDesc("Where the compiled HTML, PDF and DOCX are written, relative to the vault root.")
      .addText((text) =>
        text
          .setValue(this.plugin.settings.outputFolder)
          .onChange(async (value) => {
            this.plugin.settings.outputFolder = value.trim() || "Manuscript Output";
            await this.plugin.saveSettings();
          }),
      );

    // --- Typesetting ---------------------------------------------------------
    new Setting(containerEl).setName("Typesetting").setHeading();

    new Setting(containerEl)
      .setName("Citation style")
      .setDesc("How [@key] renders, and how the bibliography is ordered.")
      .addDropdown((d) =>
        d
          .addOption("author-date", "Author–date  (Smith 2019)")
          .addOption("numeric", "Numeric  [1]")
          .setValue(this.plugin.settings.citationStyle)
          .onChange(async (value) => {
            this.plugin.settings.citationStyle = value as CompileOptions["citationStyle"];
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Figure numbering")
      .setDesc("Continuous across the book, or restarting inside each chapter.")
      .addDropdown((d) =>
        d
          .addOption("by-chapter", "By chapter  (Figure 3.1)")
          .addOption("continuous", "Continuous  (Figure 12)")
          .setValue(this.plugin.settings.figureNumbering)
          .onChange(async (value) => {
            this.plugin.settings.figureNumbering = value as CompileOptions["figureNumbering"];
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Notes")
      .setDesc(
        "Real Word footnotes at the foot of the page, or collected endnotes in a back-matter section. Numbering is continuous across the whole book either way.",
      )
      .addDropdown((d) =>
        d
          .addOption("footnote", "Footnotes (page foot)")
          .addOption("endnote", "Endnotes (back matter)")
          .setValue(this.plugin.settings.footnotePlacement)
          .onChange(async (value) => {
            this.plugin.settings.footnotePlacement = value as CompileOptions["footnotePlacement"];
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Table of contents depth")
      .setDesc("Heading levels to include. 0 leaves the table of contents out entirely.")
      .addSlider((s) =>
        s
          .setLimits(0, 4, 1)
          .setValue(this.plugin.settings.tocDepth)
          .setDynamicTooltip()
          .onChange(async (value) => {
            this.plugin.settings.tocDepth = value;
            await this.plugin.saveSettings();
          }),
      );

    for (const [key, name, desc] of [
      ["titlePage", "Title page", "Generate a title page from the spine's frontmatter."],
      ["copyrightPage", "Copyright page", "Generate a copyright page."],
      ["listOfFigures", "List of figures", "Add a list of figures after the contents."],
      [
        "bibliographySection",
        "Bibliography section",
        "Print the reference list. Only entries the book actually cites are included.",
      ],
      [
        "pageBreakPerChapter",
        "Page break per chapter",
        "Start every chapter on a new page. These are real Word page breaks, not blank paragraphs.",
      ],
    ] as const) {
      new Setting(containerEl)
        .setName(name)
        .setDesc(desc)
        .addToggle((t) =>
          t.setValue(this.plugin.settings[key] as boolean).onChange(async (value) => {
            (this.plugin.settings[key] as boolean) = value;
            await this.plugin.saveSettings();
          }),
        );
    }

    new Setting(containerEl)
      .setName("Paper size")
      .addDropdown((d) =>
        d
          .addOption("A4", "A4")
          .addOption("Letter", "Letter")
          .addOption("A3", "A3")
          .addOption("Legal", "Legal")
          .setValue(this.plugin.settings.paperSize)
          .onChange(async (value) => {
            this.plugin.settings.paperSize = value as ManuscriptSettings["paperSize"];
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Strict mode")
      .setDesc(
        "Treat warnings as failures. With this on, a compile with an uncaptioned figure or an uncited reference will not report success.",
      )
      .addToggle((t) =>
        t.setValue(this.plugin.settings.strict).onChange(async (value) => {
          this.plugin.settings.strict = value;
          await this.plugin.saveSettings();
        }),
      );

    // --- SuperDocs -----------------------------------------------------------
    new Setting(containerEl).setName("SuperDocs").setHeading();

    containerEl.createEl("p", {
      cls: "setting-item-description",
      text:
        "Compiling is free and offline. SuperDocs is used for two things: rendering the PDF and DOCX, and the optional editorial passes. Exports do not consume operations; editorial passes cost one each.",
    });

    new Setting(containerEl)
      .setName("API key")
      .setDesc(
        "From use.superdocs.app → Settings → API Keys. Stored in this vault's plugin data, so treat the vault as you would treat the key.",
      )
      .addText((text) => {
        text.inputEl.type = "password";
        text.inputEl.autocomplete = "off";
        text
          .setPlaceholder("sk-...")
          .setValue(this.plugin.settings.apiKey)
          .onChange(async (value) => {
            this.plugin.settings.apiKey = value.trim();
            await this.plugin.saveSettings();
          });
      })
      .addButton((b) =>
        b.setButtonText("Test").onClick(async () => {
          b.setDisabled(true);
          try {
            const ok = await this.plugin.verifyKey();
            new Notice(
              ok
                ? "SuperDocs key works."
                : "SuperDocs rejected that key. Check it at use.superdocs.app → Settings → API Keys.",
            );
          } catch (err) {
            new Notice(`Could not reach SuperDocs: ${err instanceof Error ? err.message : err}`);
          } finally {
            b.setDisabled(false);
          }
        }),
      );

    new Setting(containerEl)
      .setName("Confirm before spending")
      .setDesc(
        "Show what an editorial pass will send and what it will cost, and wait for a yes. Leave this on.",
      )
      .addToggle((t) =>
        t.setValue(this.plugin.settings.confirmSpend).onChange(async (value) => {
          this.plugin.settings.confirmSpend = value;
          await this.plugin.saveSettings();
        }),
      );

    const spend = containerEl.createEl("p", { cls: "setting-item-description" });
    spend.setText(
      `This plugin has spent ${this.plugin.settings.operationsSpent} SuperDocs operation${
        this.plugin.settings.operationsSpent === 1 ? "" : "s"
      } from this vault.${
        this.plugin.settings.lastKnownRemaining !== null
          ? ` Last reported remaining: ${this.plugin.settings.lastKnownRemaining}.`
          : ""
      }`,
    );

    // --- Workflow ------------------------------------------------------------
    new Setting(containerEl).setName("Workflow").setHeading();

    new Setting(containerEl)
      .setName("Recompile on save")
      .setDesc(
        "Recompile when a note on the spine is saved. Compiling is local and incremental, so this is cheap — but it is off by default because a 300-chapter book on a slow disk is still work.",
      )
      .addToggle((t) =>
        t.setValue(this.plugin.settings.compileOnSave).onChange(async (value) => {
          this.plugin.settings.compileOnSave = value;
          await this.plugin.saveSettings();
        }),
      );

    if (this.plugin.settings.pendingJob) {
      const job = this.plugin.settings.pendingJob;
      new Setting(containerEl)
        .setName("Unfinished review")
        .setDesc(
          `"${job.instruction}" was started on ${new Date(
            job.startedAt,
          ).toLocaleString()} and is still waiting for your decision.`,
        )
        .addButton((b) =>
          b
            .setButtonText("Resume")
            .setCta()
            .onClick(() => void this.plugin.resumePendingJob()),
        )
        .addButton((b) =>
          b.setButtonText("Discard").onClick(async () => {
            await this.plugin.discardPendingJob();
            this.display();
          }),
        );
    }
  }
}
