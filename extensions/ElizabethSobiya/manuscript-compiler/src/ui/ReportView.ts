/**
 * The compile report.
 *
 * This is the surface where the plugin is either honest or not. It shows what the
 * compile produced, what it could not resolve, and — the part that matters for a
 * long book — exactly which chapters this recompile touched and why.
 *
 * Diagnostics are clickable: each one opens the note at the offending line.
 */

import { ItemView, WorkspaceLeaf, TFile } from "obsidian";
import type { CompileOutput } from "../core/compile";
import { summariseChanges } from "../core/cache";
import type { Diagnostic } from "../core/types";
import type { EditorialPass } from "../superdocs/editorial";

export const REPORT_VIEW_TYPE = "manuscript-compile-report";

export interface ReportActions {
  compile: () => void;
  exportBook: (formats: Array<"pdf" | "docx" | "html">) => void;
  runPass: (pass: EditorialPass) => void;
  passes: EditorialPass[];
}

export class CompileReportView extends ItemView {
  private result: CompileOutput | null = null;
  private error: string | null = null;
  private busy = "";
  private idle = "";
  private onCancel: (() => void) | null = null;
  /**
   * The live busy line, kept as a node so progress can be written into it directly.
   *
   * Progress fires once per stage and once per uploaded figure — 120 times for an
   * illustrated book. Re-running render() for each of those tore down and rebuilt
   * the whole panel, which flickers, drops frames, and re-creates the Compile
   * button underneath the user's cursor mid-click.
   */
  private busyTextEl: HTMLElement | null = null;

  constructor(
    leaf: WorkspaceLeaf,
    private readonly actions: ReportActions,
  ) {
    super(leaf);
  }

  getViewType(): string {
    return REPORT_VIEW_TYPE;
  }

  getDisplayText(): string {
    return "Manuscript";
  }

  override getIcon(): string {
    return "book-open";
  }

  setBusy(message: string, onCancel?: () => void): void {
    const wasBusy = this.busy !== "";
    this.busy = message;
    this.idle = "";
    if (onCancel) this.onCancel = onCancel;
    // Already showing the busy panel: update the one line that changed.
    if (wasBusy && this.busyTextEl) {
      this.busyTextEl.textContent = message;
      return;
    }
    this.render();
  }

  setResult(result: CompileOutput): void {
    this.result = result;
    this.error = null;
    this.busy = "";
    this.idle = "";
    this.onCancel = null;
    this.render();
  }

  setError(message: string): void {
    this.error = message;
    this.busy = "";
    this.idle = "";
    this.onCancel = null;
    this.render();
  }

  /** Leave the last good report on screen with a short status line above it. */
  setIdle(message: string): void {
    this.busy = "";
    this.idle = message;
    this.onCancel = null;
    this.render();
  }

  override async onOpen(): Promise<void> {
    this.render();
  }

  private render(): void {
    const root = this.containerEl.children[1] as HTMLElement;
    root.empty();
    root.addClass("mc-report");

    const header = root.createDiv({ cls: "mc-report-header" });
    header.createEl("h3", { text: "Manuscript Compiler" });

    const actions = header.createDiv({ cls: "mc-report-actions" });
    const compileBtn = actions.createEl("button", { text: "Compile", cls: "mod-cta" });
    compileBtn.setAttr("aria-label", "Compile the manuscript without exporting");
    compileBtn.addEventListener("click", () => this.actions.compile());
    const exportBtn = actions.createEl("button", { text: "Compile & export" });
    exportBtn.setAttr("aria-label", "Compile and export as PDF and DOCX");
    exportBtn.addEventListener("click", () => this.actions.exportBook(["pdf", "docx", "html"]));

    if (this.busy) {
      const box = root.createDiv({ cls: "mc-busy" });
      this.busyTextEl = box.createDiv({ cls: "mc-busy-text", text: this.busy });
      if (this.onCancel) {
        const cancel = box.createEl("button", { text: "Cancel", cls: "mc-cancel" });
        cancel.setAttr("aria-label", "Cancel the running compile");
        cancel.addEventListener("click", () => {
          this.busyTextEl?.setText("Cancelling…");
          this.onCancel?.();
        });
      }
      return;
    }
    this.busyTextEl = null;

    if (this.idle) {
      root.createDiv({ cls: "mc-idle", text: this.idle });
    }

    if (this.error) {
      const box = root.createDiv({ cls: "mc-error-box" });
      box.createEl("strong", { text: "Compile failed" });
      box.createEl("p", { text: this.error });
      return;
    }

    if (!this.result) {
      root.createEl("p", {
        cls: "mc-empty",
        text: "Compile the manuscript to see its report here — word count, figure and footnote numbering, unresolved citations, and exactly which chapters a recompile touched.",
      });
      return;
    }

    this.renderStats(root, this.result);
    this.renderIncremental(root, this.result);
    this.renderDiagnostics(root, this.result.diagnostics);
    this.renderPasses(root);
  }

  private renderStats(root: HTMLElement, result: CompileOutput): void {
    const meta = root.createDiv({ cls: "mc-meta" });
    meta.createEl("div", { cls: "mc-book-title", text: result.meta.title });
    if (result.meta.author) meta.createEl("div", { cls: "mc-book-author", text: result.meta.author });

    const grid = root.createDiv({ cls: "mc-stats" });
    const stat = (label: string, value: string) => {
      const cell = grid.createDiv({ cls: "mc-stat" });
      cell.createDiv({ cls: "mc-stat-value", text: value });
      cell.createDiv({ cls: "mc-stat-label", text: label });
    };
    stat("chapters", String(result.stats.chapters));
    stat("words", result.stats.words.toLocaleString());
    stat("pages (est.)", String(result.stats.estimatedPages));
    stat("figures", String(result.stats.figures));
    stat("footnotes", String(result.stats.footnotes));
    stat("citations", String(result.stats.citations));

    const total = result.timings.reduce((n, t) => n + t.ms, 0);
    root.createDiv({
      cls: "mc-timings",
      text: `compiled in ${total.toFixed(0)}ms · ${result.timings
        .filter((t) => t.ms >= 1)
        .map((t) => `${t.stage} ${t.ms.toFixed(0)}ms`)
        .join(" · ")}`,
    });
  }

  private renderIncremental(root: HTMLElement, result: CompileOutput): void {
    const counts = summariseChanges(result.changes);
    const section = root.createDiv({ cls: "mc-section" });
    section.createEl("h4", { text: "What this recompile changed" });

    if (counts.added === result.changes.length) {
      section.createEl("p", {
        cls: "mc-note",
        text: "First compile of this manuscript — every chapter was rendered.",
      });
      return;
    }

    section.createEl("p", {
      cls: "mc-note",
      text:
        `${counts.unchanged} chapter${counts.unchanged === 1 ? "" : "s"} came through byte for byte. ` +
        `${counts.rewritten} re-rendered, ${counts.renumbered} kept their prose but moved numbers, ` +
        `${counts.added} added, ${counts.removed} removed.`,
    });

    const moved = result.changes.filter((c) => c.kind !== "unchanged");
    if (moved.length === 0) return;
    const list = section.createEl("ul", { cls: "mc-change-list" });
    for (const change of moved.slice(0, 40)) {
      const li = list.createEl("li");
      li.createSpan({ cls: `mc-kind mc-kind-${change.kind}`, text: change.kind });
      li.createSpan({ cls: "mc-change-title", text: change.title });
      if (change.reason) li.createSpan({ cls: "mc-change-reason", text: change.reason });
    }
    if (moved.length > 40) {
      section.createEl("p", { cls: "mc-note", text: `…and ${moved.length - 40} more.` });
    }
  }

  private renderDiagnostics(root: HTMLElement, diagnostics: Diagnostic[]): void {
    const section = root.createDiv({ cls: "mc-section" });
    const errors = diagnostics.filter((d) => d.severity === "error");
    const warnings = diagnostics.filter((d) => d.severity === "warning");
    const infos = diagnostics.filter((d) => d.severity === "info");

    // Infos are rendered below alongside errors and warnings, so they have to be
    // counted here too — a header that says "1 warning" above two cards reads as a bug.
    const counts = [
      `${errors.length} error${errors.length === 1 ? "" : "s"}`,
      `${warnings.length} warning${warnings.length === 1 ? "" : "s"}`,
    ];
    if (infos.length > 0) {
      counts.push(`${infos.length} note${infos.length === 1 ? "" : "s"}`);
    }
    section.createEl("h4", { text: `Findings — ${counts.join(", ")}` });

    if (diagnostics.length === 0) {
      section.createEl("p", {
        cls: "mc-clean",
        text: "Nothing to report. Every chapter resolved, every citation found its entry, every cross-reference found its target.",
      });
      return;
    }

    const list = section.createEl("ul", { cls: "mc-diagnostics" });
    for (const d of [...errors, ...warnings, ...infos]) {
      const li = list.createEl("li", { cls: `mc-diag mc-diag-${d.severity}` });
      li.createSpan({ cls: "mc-diag-code", text: d.code });
      li.createSpan({ cls: "mc-diag-message", text: d.message });
      if (d.file) {
        const link = li.createEl("a", {
          cls: "mc-diag-file",
          text: `${d.file}${d.line ? `:${d.line}` : ""}`,
        });
        link.addEventListener("click", (evt) => {
          evt.preventDefault();
          void this.openAt(d);
        });
      }
      if (d.snippet) li.createEl("code", { cls: "mc-diag-snippet", text: d.snippet });
    }
  }

  private async openAt(d: Diagnostic): Promise<void> {
    if (!d.file) return;
    const file = this.app.vault.getAbstractFileByPath(d.file);
    if (!(file instanceof TFile)) return;
    const leaf = this.app.workspace.getLeaf(false);
    await leaf.openFile(file);
    if (d.line && d.line > 0) {
      const view = leaf.view as unknown as { editor?: { setCursor: (p: { line: number; ch: number }) => void } };
      view.editor?.setCursor({ line: d.line - 1, ch: 0 });
    }
  }

  private renderPasses(root: HTMLElement): void {
    const section = root.createDiv({ cls: "mc-section" });
    section.createEl("h4", { text: "Editorial passes" });
    section.createEl("p", {
      cls: "mc-note",
      text: "These call SuperDocs and cost operations. Each one shows what it will send before it runs, and every change it proposes is reviewed before it lands.",
    });
    const list = section.createDiv({ cls: "mc-pass-list" });
    for (const pass of this.actions.passes) {
      const row = list.createDiv({ cls: "mc-pass" });
      const button = row.createEl("button", { text: pass.title });
      button.addEventListener("click", () => this.actions.runPass(pass));
      row.createSpan({ cls: "mc-pass-desc", text: pass.description });
      row.createSpan({
        cls: "mc-pass-cost",
        text: `${pass.estimatedOperations} op${pass.estimatedOperations === 1 ? "" : "s"}`,
      });
    }
  }
}
