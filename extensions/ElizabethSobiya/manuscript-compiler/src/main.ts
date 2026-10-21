/**
 * Manuscript Compiler for Obsidian.
 *
 * Define the spine — one index note listing your chapters in order — and this
 * turns a vault into a book: chapters in order, heading levels normalised,
 * front and back matter generated, footnotes converted from inline notes,
 * figures captioned and numbered continuously, citations resolved from a .bib
 * file, and a table of contents built. Output is a print-ready PDF and a DOCX
 * an editor can mark up, rendered by SuperDocs.
 *
 * The division of labour, which is the main design decision in this plugin:
 * compiling is deterministic, local, incremental and free; SuperDocs renders the
 * final files and runs the optional editorial passes. Typesetting a book is not
 * a job for a language model, and paying per compile would make a 300-page book
 * unaffordable to iterate on.
 */

import { Notice, Plugin, TFile, WorkspaceLeaf, normalizePath } from "obsidian";
import { compile, type CompileOutput } from "./core/compile";
import { summariseChanges } from "./core/cache";
import { renderStandaloneHtml } from "./core/standalone";
import { DEFAULT_SETTINGS, ManuscriptSettingTab, type ManuscriptSettings } from "./settings";
import { SuperDocsClient, SuperDocsError, type Usage } from "./superdocs/client";
import { obsidianTransport } from "./superdocs/obsidian-transport";
import { uploadFigures } from "./superdocs/figures";
import { PASSES, finalisePlan, planPass, type EditorialPass, type PassId } from "./superdocs/editorial";
import { applyApprovedChanges, extractPendingChanges, pollJob, type PendingJob } from "./superdocs/jobs";
import { ObsidianVault } from "./vault/obsidian-vault";
import { CompileReportView, REPORT_VIEW_TYPE } from "./ui/ReportView";
import { ReviewModal } from "./ui/ReviewModal";
import { ConfirmSpendModal } from "./ui/ConfirmSpendModal";
import { hash } from "./core/util";
import { mergeRequests, type CompileRequest } from "./core/requests";

const MANIFEST_PATH = ".manuscript-cache/manifest.json";

export default class ManuscriptCompilerPlugin extends Plugin {
  settings!: ManuscriptSettings;
  private lastResult: CompileOutput | null = null;
  private compiling = false;
  private statusBar: HTMLElement | null = null;
  private saveDebounce: number | null = null;
  /**
   * A compile requested while one was already running. Dropping it silently was a
   * real bug: compile-on-save debounces 1.5s, a cold compile takes several seconds,
   * so any edit made *during* a compile was discarded and never compiled. The
   * output then disagreed with the vault with nothing on screen to say so.
   * Requests coalesce into one trailing run rather than queueing a backlog.
   */
  private pendingRecompile: CompileRequest | null = null;
  private activeCompile: AbortController | null = null;
  private disposed = false;

  override async onload(): Promise<void> {
    await this.loadSettings();

    this.registerView(
      REPORT_VIEW_TYPE,
      (leaf: WorkspaceLeaf) =>
        new CompileReportView(leaf, {
          compile: () => void this.runCompile(),
          exportBook: (formats) => void this.runCompile({ exportFormats: formats }),
          runPass: (pass) => void this.runEditorialPass(pass.id),
          passes: Object.values(PASSES),
        }),
    );

    this.addRibbonIcon("book-open", "Compile manuscript", () => void this.runCompile());
    this.statusBar = this.addStatusBarItem();

    this.addCommand({
      id: "compile-manuscript",
      name: "Compile manuscript",
      callback: () => void this.runCompile(),
    });

    this.addCommand({
      id: "compile-and-export",
      name: "Compile and export (PDF + DOCX)",
      callback: () => void this.runCompile({ exportFormats: ["pdf", "docx", "html"] }),
    });

    this.addCommand({
      id: "open-report",
      name: "Open compile report",
      callback: () => void this.activateReport(),
    });

    this.addCommand({
      id: "check-manuscript",
      name: "Check manuscript (no export)",
      callback: () => void this.runCompile({ quiet: false }),
    });

    for (const pass of Object.values(PASSES)) {
      this.addCommand({
        id: `pass-${pass.id}`,
        name: `Editorial: ${pass.title}`,
        callback: () => void this.runEditorialPass(pass.id),
      });
    }

    this.addCommand({
      id: "resume-review",
      name: "Resume unfinished review",
      checkCallback: (checking) => {
        if (!this.settings.pendingJob) return false;
        if (!checking) void this.resumePendingJob();
        return true;
      },
    });

    this.addSettingTab(new ManuscriptSettingTab(this.app, this));

    // Recompile on save, when asked for. Debounced, because Obsidian fires modify
    // on every keystroke burst and a book is not a scratch note.
    this.registerEvent(
      this.app.vault.on("modify", (file) => {
        if (!this.settings.compileOnSave || !(file instanceof TFile)) return;
        if (file.extension !== "md") return;
        if (this.saveDebounce !== null) window.clearTimeout(this.saveDebounce);
        this.saveDebounce = window.setTimeout(() => void this.runCompile({ quiet: true }), 1500);
      }),
    );

    if (this.settings.pendingJob) {
      new Notice(
        "Manuscript Compiler: a review from your last session is still waiting. Run “Resume unfinished review”.",
        8000,
      );
    }

    this.updateStatusBar("ready");
  }

  override onunload(): void {
    // Teardown has to stop work that is already in flight, not just cancel work
    // that has not started. Without this, disabling the plugin mid-export leaves a
    // promise chain that still shows notices, still writes files into the vault and
    // still persists settings — all on behalf of a plugin that no longer exists.
    this.disposed = true;
    this.pendingRecompile = null;
    if (this.saveDebounce !== null) window.clearTimeout(this.saveDebounce);
    this.activeCompile?.abort();
    this.activeCompile = null;
  }

  /** A notice, unless we have been torn down. */
  private notify(message: string, timeout?: number): void {
    if (this.disposed) return;
    new Notice(message, timeout);
  }

  cancelCompile(): void {
    this.pendingRecompile = null;
    this.activeCompile?.abort();
  }

  // --- settings --------------------------------------------------------------

  async loadSettings(): Promise<void> {
    this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
  }

  async saveSettings(): Promise<void> {
    await this.saveData(this.settings);
  }

  private client(): SuperDocsClient {
    if (!this.settings.apiKey) {
      throw new Error(
        "No SuperDocs API key set. Open Settings → Manuscript Compiler and paste one, or compile without exporting — compiling never needs a key.",
      );
    }
    return new SuperDocsClient({
      apiKey: this.settings.apiKey,
      apiBase: this.settings.apiBase,
      transport: obsidianTransport,
      onUsage: (usage) => void this.recordUsage(usage),
    });
  }

  async verifyKey(): Promise<boolean> {
    return this.client().verifyKey();
  }

  private async recordUsage(usage: Usage): Promise<void> {
    if (usage.ops_charged) this.settings.operationsSpent += usage.ops_charged;
    if (typeof usage.monthly_remaining === "number") {
      this.settings.lastKnownRemaining = usage.monthly_remaining;
    }
    await this.saveSettings();
    this.updateStatusBar("ready");
  }

  private updateStatusBar(state: string): void {
    if (!this.statusBar) return;
    const remaining =
      this.settings.lastKnownRemaining !== null ? ` · ${this.settings.lastKnownRemaining} ops left` : "";
    this.statusBar.setText(
      state === "ready"
        ? `Manuscript${this.lastResult ? `: ${this.lastResult.stats.estimatedPages}pp` : ""}${remaining}`
        : `Manuscript: ${state}`,
    );
  }

  // --- report view -----------------------------------------------------------

  private async activateReport(): Promise<CompileReportView | null> {
    const existing = this.app.workspace.getLeavesOfType(REPORT_VIEW_TYPE);
    if (existing.length > 0) {
      await this.app.workspace.revealLeaf(existing[0]!);
      return existing[0]!.view as CompileReportView;
    }
    const leaf = this.app.workspace.getRightLeaf(false);
    if (!leaf) return null;
    await leaf.setViewState({ type: REPORT_VIEW_TYPE, active: true });
    await this.app.workspace.revealLeaf(leaf);
    return leaf.view as CompileReportView;
  }

  private reportView(): CompileReportView | null {
    const leaves = this.app.workspace.getLeavesOfType(REPORT_VIEW_TYPE);
    return leaves.length ? (leaves[0]!.view as CompileReportView) : null;
  }

  // --- compile ---------------------------------------------------------------

  async runCompile(opts: CompileRequest = {}): Promise<CompileOutput | null> {
    if (this.disposed) return null;

    if (this.compiling) {
      // Coalesce rather than drop. The old code returned here, which meant an edit
      // made while a compile was running was never compiled at all.
      this.pendingRecompile = mergeRequests(this.pendingRecompile, opts);
      if (!opts.quiet) new Notice("A compile is already running — this one is queued.");
      return null;
    }

    this.compiling = true;
    const controller = new AbortController();
    this.activeCompile = controller;

    // A silent background recompile must not steal the sidebar. Only an explicit
    // compile opens the panel; a quiet one updates it if it happens to be open.
    const view = opts.quiet ? this.reportView() : await this.activateReport();
    view?.setBusy("Compiling…", () => this.cancelCompile());
    this.updateStatusBar("compiling");

    try {
      const vault = new ObsidianVault(this.app);
      const manifestJson = await this.readManifest();
      const result = await compile({
        vault,
        options: this.settings,
        manifestJson,
        signal: controller.signal,
        onProgress: (stage, detail) =>
          view?.setBusy(`${stage}: ${detail ?? ""}`, () => this.cancelCompile()),
      });
      if (this.disposed) return null;

      this.lastResult = result;
      view?.setResult(result);
      await this.writeManifest(result.manifest);
      await this.writeOutput(`${slugFilename(result.meta.title)}.html`, renderStandaloneHtml(result.html, result.meta));

      if (!opts.quiet) {
        const counts = summariseChanges(result.changes);
        const errors = result.diagnostics.filter((d) => d.severity === "error").length;
        // A success message must only ever mean success. When something did not
        // resolve, the notice says so and the report has the detail.
        this.notify(
          errors > 0
            ? `Compiled with ${errors} unresolved item${errors === 1 ? "" : "s"} — see the report. ` +
              `${result.stats.chapters} chapters, ~${result.stats.estimatedPages} pages.`
            : `Compiled ${result.stats.chapters} chapters, ~${result.stats.estimatedPages} pages. ` +
              `${counts.unchanged} unchanged, ${counts.rewritten} re-rendered.`,
          6000,
        );
      }

      if (opts.exportFormats?.length) {
        await this.exportBook(result, opts.exportFormats);
      }

      this.updateStatusBar("ready");
      return result;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      // A cancelled compile is an outcome the user asked for, not a failure.
      if (controller.signal.aborted || (err as Error)?.name === "Aborted") {
        view?.setIdle("Compile cancelled. Nothing was written.");
        this.updateStatusBar("ready");
        return null;
      }
      view?.setError(message);
      this.notify(`Manuscript compile failed: ${message}`, 10000);
      this.updateStatusBar("failed");
      return null;
    } finally {
      this.compiling = false;
      this.activeCompile = null;
      const queued = this.pendingRecompile;
      this.pendingRecompile = null;
      // Run the trailing request once, after this one has fully settled.
      if (queued && !this.disposed) void this.runCompile(queued);
    }
  }

  private async exportBook(
    result: CompileOutput,
    formats: Array<"pdf" | "docx" | "html">,
  ): Promise<void> {
    const remote = formats.filter((f) => f !== "html");
    if (remote.length === 0) return;

    const view = this.reportView();
    let client: SuperDocsClient;
    try {
      client = this.client();
    } catch (err) {
      new Notice(err instanceof Error ? err.message : String(err), 8000);
      return;
    }

    // Exports are the longest operation the plugin performs; they get the same
    // cancellation path as a compile.
    const exportController = new AbortController();
    this.activeCompile = exportController;
    const exportSignal = exportController.signal;

    view?.setBusy("Uploading figures…", () => this.cancelCompile());
    const uploaded = await uploadFigures({
      html: result.html,
      figures: result.assignedFigures,
      vault: new ObsidianVault(this.app),
      client,
      cache: result.manifest.imageUrls,
      signal: exportSignal,
      onProgress: (done, total) =>
        view?.setBusy(`Uploading figures ${done}/${total}…`, () => this.cancelCompile()),
    });
    if (this.disposed || exportSignal.aborted) return;
    if (uploaded.diagnostics.length) {
      result.diagnostics.push(...uploaded.diagnostics);
      view?.setResult(result);
    }
    await this.writeManifest(result.manifest);

    const base = slugFilename(result.meta.title);
    for (const format of remote) {
      view?.setBusy(`Rendering ${format.toUpperCase()}… (a long book can take a few minutes)`);
      try {
        const exported = await client.exportDocument({
          format,
          html: uploaded.html,
          options: {
            paper_size: this.settings.paperSize,
            margins: this.settings.margins,
            filename: base,
          },
        });
        const path = await this.writeBinaryOutput(`${base}.${format}`, exported.bytes);

        // Only claim success once the file is actually on disk with bytes in it.
        const written = this.app.vault.getAbstractFileByPath(path);
        const size = written instanceof TFile ? written.stat.size : 0;
        if (size <= 0) {
          new Notice(`${format.toUpperCase()} export wrote an empty file. Nothing was overwritten.`, 8000);
          continue;
        }
        const warnings = exported.warnings.length
          ? ` (${exported.warnings.length} export warning${exported.warnings.length === 1 ? "" : "s"} — see the report)`
          : "";
        new Notice(`Wrote ${path} · ${(size / 1024).toFixed(0)} KB${warnings}`, 6000);
        for (const w of exported.warnings) {
          result.diagnostics.push({
            severity: "warning",
            code: `export.${w.code}`,
            message: w.message,
          });
        }
      } catch (err) {
        const message = err instanceof SuperDocsError ? `${err.message} (HTTP ${err.status})` : String(err);
        new Notice(`${format.toUpperCase()} export failed: ${message}`, 10000);
        result.diagnostics.push({
          severity: "error",
          code: "export.failed",
          message: `${format.toUpperCase()} export failed: ${message}`,
        });
      }
    }
    view?.setResult(result);
  }

  // --- editorial passes -------------------------------------------------------

  async runEditorialPass(passId: PassId): Promise<void> {
    const pass: EditorialPass = PASSES[passId];
    const result = this.lastResult ?? (await this.runCompile({ quiet: true }));
    if (!result) return;

    let client: SuperDocsClient;
    try {
      client = this.client();
    } catch (err) {
      new Notice(err instanceof Error ? err.message : String(err), 8000);
      return;
    }

    const chapterHtml = result.spine.map(
      (entry) => result.manifest.renders[entry.path] ?? "",
    );
    const plan = finalisePlan(
      planPass({ pass: passId, compiled: result, chapterHtml }),
    );

    if (this.settings.confirmSpend) {
      const ok = await new ConfirmSpendModal(
        this.app,
        pass.title,
        plan,
        this.settings.lastKnownRemaining,
      ).ask();
      if (!ok) return;
    }

    const view = this.reportView();
    view?.setBusy(`${pass.title}… (this can take a few minutes on a long document)`);

    // A fresh session per pass. A stable id looks tidy and is wrong: the API
    // answers 409 when a second turn arrives while the first is still settling,
    // and server-side context from an unrelated pass leaks into the next one —
    // a blurb request inheriting the preface conversation. The CLI round trip
    // learned this against the live API; the plugin was still doing it the old way.
    const sessionId = `manuscript-${hash(result.meta.title)}-${Date.now().toString(36)}`;
    try {
      // Upload first, then chat. The document has to be the session's active
      // document before a turn can edit it — passing the HTML inline on the chat
      // call is not the same thing, and is why this path failed.
      view?.setBusy(`${pass.title}: uploading the manuscript…`, () => this.cancelCompile());
      await client.uploadDocument({
        sessionId,
        filename: `${slugFilename(result.meta.title)}.html`,
        content: plan.documentHtml,
        contentType: "text/html",
      });

      view?.setBusy(`${pass.title}: starting…`, () => this.cancelCompile());
      const { job_id } = await client.chatAsync({
        sessionId,
        message: plan.instruction,
        approvalMode: "ask_every_time",
      });

      const pending: PendingJob = {
        jobId: job_id,
        sessionId,
        instruction: pass.title,
        startedAt: new Date().toISOString(),
        documentHash: hash(plan.documentHtml),
      };
      // Checkpoint before waiting: if Obsidian closes now, the review is recoverable.
      this.settings.pendingJob = pending;
      await this.saveSettings();

      await this.driveJob(client, pending, plan.documentHtml);
    } catch (err) {
      const message = err instanceof SuperDocsError ? `${err.message} (HTTP ${err.status})` : String(err);
      new Notice(`${pass.title} failed: ${message}`, 10000);
    } finally {
      view?.setResult(result);
    }
  }

  /**
   * Drive one job to a conclusion, pausing at the human gate.
   *
   * Called both by a fresh pass and by "resume", which is why it takes the pending
   * record rather than closing over local state.
   */
  private async driveJob(
    client: SuperDocsClient,
    pending: PendingJob,
    documentHtml: string,
  ): Promise<void> {
    const view = this.reportView();
    let html = documentHtml;
    let applied = false;

    for (let round = 0; round < 5; round += 1) {
      const outcome = await pollJob(client, pending.jobId, {
        onTick: (job, elapsed) =>
          view?.setBusy(`${pending.instruction}: ${job.status} · ${Math.round(elapsed / 1000)}s`),
      });

      if (outcome.kind === "failed") {
        await this.discardPendingJob();
        new Notice(`${pending.instruction} failed: ${outcome.error}`, 10000);
        return;
      }
      if (outcome.kind === "cancelled") {
        await this.discardPendingJob();
        new Notice(`${pending.instruction} was cancelled. Nothing was changed.`);
        return;
      }
      if (outcome.kind === "continue_prompt") {
        await this.discardPendingJob();
        new Notice(
          `${pending.instruction} paused because the edit is large. The work done so far was kept; run the pass again to continue.`,
          10000,
        );
        return;
      }
      if (outcome.kind === "completed") {
        await this.discardPendingJob();
        const updated = outcome.job.result?.document_changes?.updated_html;
        if (updated) {
          await this.writeEditorialOutput(pending, updated);
        } else if (applied) {
          // No authoritative HTML came back, but changes were approved. Fall back
          // to the copy we applied them to locally, and say which one this is.
          await this.writeEditorialOutput(pending, html);
        } else {
          new Notice(`${pending.instruction} finished with nothing to change.`);
        }
        return;
      }

      // awaiting_approval — the gate.
      const changes = outcome.changes.length ? outcome.changes : extractPendingChanges(outcome.job);
      if (changes.length === 0) {
        new Notice(
          "SuperDocs is waiting for approval but sent no changes to review. The job was left open; nothing was applied.",
          10000,
        );
        return;
      }

      const review = await new ReviewModal(this.app, pending.instruction, changes).waitForDecision();
      if (review.deferred || review.decisions.length === 0) {
        new Notice(
          "Review left open. Nothing was applied. Run “Resume unfinished review” when you are ready.",
          8000,
        );
        return;
      }

      await client.approve({
        sessionId: pending.sessionId,
        jobId: pending.jobId,
        decisions: review.decisions,
      });

      const approvals = new Map(review.decisions.map((d) => [d.changeId, d.approved]));
      if (html) {
        const result = applyApprovedChanges(html, changes, approvals);
        html = result.html;
        applied = applied || result.applied > 0;
      }

      const accepted = review.decisions.filter((d) => d.approved).length;
      const rejected = review.decisions.length - accepted;
      new Notice(
        `${accepted} change${accepted === 1 ? "" : "s"} accepted, ${rejected} rejected.` +
          (rejected > 0 ? " Rejections were sent back with your notes." : ""),
        6000,
      );

      // Do not write anything here. The server holds the authoritative document,
      // and the next poll returns it as `updated_html` once the job settles — or
      // returns another round of proposals, which needs the gate again. Writing
      // from the locally-applied copy at this point was a real bug on the resume
      // path, where there is no local copy to apply changes to and the output
      // would have been an empty file.
    }

    new Notice("Stopped after five review rounds. The job is still open; nothing further was applied.", 10000);
  }

  async resumePendingJob(): Promise<void> {
    const pending = this.settings.pendingJob;
    if (!pending) {
      new Notice("No unfinished review.");
      return;
    }
    try {
      const client = this.client();
      const job = await client.getJob(pending.jobId);
      if (job.status === "completed" || job.status === "failed" || job.status === "cancelled") {
        await this.discardPendingJob();
        new Notice(`That review is already ${job.status}. Nothing left to decide.`);
        return;
      }
      await this.driveJob(client, pending, "");
    } catch (err) {
      const message = err instanceof SuperDocsError ? `${err.message} (HTTP ${err.status})` : String(err);
      new Notice(`Could not resume the review: ${message}`, 10000);
    }
  }

  async discardPendingJob(): Promise<void> {
    this.settings.pendingJob = null;
    await this.saveSettings();
  }

  private async writeEditorialOutput(pending: PendingJob, html: string): Promise<void> {
    const name = `${slugFilename(pending.instruction)}-${pending.startedAt.slice(0, 10)}.html`;
    const path = await this.writeOutput(name, html);
    new Notice(`Wrote ${path}. Nothing in your chapter notes was touched.`, 8000);
  }

  // --- vault IO ---------------------------------------------------------------

  private async ensureFolder(path: string): Promise<void> {
    const parts = normalizePath(path).split("/").filter(Boolean);
    let current = "";
    for (const part of parts) {
      current = current ? `${current}/${part}` : part;
      if (!this.app.vault.getAbstractFileByPath(current)) {
        await this.app.vault.createFolder(current).catch(() => undefined);
      }
    }
  }

  private async writeOutput(filename: string, content: string): Promise<string> {
    await this.ensureFolder(this.settings.outputFolder);
    const path = normalizePath(`${this.settings.outputFolder}/${filename}`);
    const existing = this.app.vault.getAbstractFileByPath(path);
    if (existing instanceof TFile) await this.app.vault.modify(existing, content);
    else await this.app.vault.create(path, content);
    return path;
  }

  private async writeBinaryOutput(filename: string, bytes: ArrayBuffer): Promise<string> {
    await this.ensureFolder(this.settings.outputFolder);
    const path = normalizePath(`${this.settings.outputFolder}/${filename}`);
    const existing = this.app.vault.getAbstractFileByPath(path);
    if (existing instanceof TFile) await this.app.vault.modifyBinary(existing, bytes);
    else await this.app.vault.createBinary(path, bytes);
    return path;
  }

  /**
   * The manifest lives in the vault's plugin data folder, not in the vault tree.
   * A book's cache is not a note, and it should not show up in search, sync
   * conflicts, or the file explorer.
   */
  private manifestPath(): string {
    return normalizePath(`${this.manifest.dir ?? ".obsidian/plugins/superdocs-manuscript-compiler"}/${MANIFEST_PATH}`);
  }

  private async readManifest(): Promise<string | null> {
    const path = this.manifestPath();
    try {
      if (!(await this.app.vault.adapter.exists(path))) return null;
      return await this.app.vault.adapter.read(path);
    } catch {
      return null;
    }
  }

  private async writeManifest(manifest: unknown): Promise<void> {
    const path = this.manifestPath();
    const dir = path.slice(0, path.lastIndexOf("/"));
    try {
      if (!(await this.app.vault.adapter.exists(dir))) {
        await this.app.vault.adapter.mkdir(dir);
      }
      await this.app.vault.adapter.write(path, JSON.stringify(manifest));
    } catch (err) {
      // A cache that cannot be written costs speed, never correctness: the next
      // compile is simply a cold one. Say so rather than failing the compile.
      console.warn("Manuscript Compiler: could not write the compile cache", err);
    }
  }
}

function slugFilename(title: string): string {
  return (
    title
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60) || "manuscript"
  );
}
