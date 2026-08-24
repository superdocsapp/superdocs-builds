import { Notice, Plugin, TFile } from "obsidian";
import { DEFAULT_SETTINGS, type JobStatus, type LivingNoteSettings, type PendingChange, type PreviewPlan } from "./types";
import { createPreviewPlan, eligibleSourceFiles, fingerprintFiles } from "./retrieval";
import { alignChunks, applyApprovedChanges, assertExportAgrees, buildRegionDocument, ownershipPrompt, parseOwnership } from "./ownership";
import { jobUsage, pendingChanges, SuperDocsClient } from "./superdocs";
import { LivingNoteSettingTab, PreviewModal, type ReviewDecision, reviewChanges, showError } from "./ui";

interface PersistedState {
  lastProcessedSourceFingerprint?: string;
  lastAttemptedSourceFingerprint?: string;
  lastSuccessfulRunAt?: number;
}

const MAX_REVIEW_ROUNDS = 3;
const DEBOUNCE_MS = 5_000;
const TICK_MS = 60_000;
const JOB_DEADLINE_MS = 15 * 60_000;

export default class SuperDocsLivingNotePlugin extends Plugin {
  override settings: LivingNoteSettings = { ...DEFAULT_SETTINGS };
  private state: PersistedState = {};
  private running = false;
  private debounceTimer?: number;
  private lastScheduledCheck = Date.now();
  private statusBar!: HTMLElement;

  // Seams so the end-to-end test can drive a run without an Obsidian window.
  review: (changes: PendingChange[], round: number, maxRounds: number) => Promise<ReviewDecision[]> =
    (changes, round, maxRounds) => reviewChanges(this.app, changes, round, maxRounds);
  showPreview: (plan: PreviewPlan) => void = (plan) => new PreviewModal(this.app, plan).open();

  override async onload(): Promise<void> {
    await this.loadSettings();
    this.statusBar = this.addStatusBarItem();
    this.setStatus("idle");
    this.addSettingTab(new LivingNoteSettingTab(this.app, this));

    this.addCommand({ id: "set-active-note-as-designated", name: "Set active note as designated living note", callback: () => void this.setActiveNoteAsTarget() });
    this.addCommand({ id: "initialize-owned-region", name: "Initialize an owned region in the designated note", callback: () => void this.initializeOwnedRegion() });
    this.addCommand({ id: "preview-living-note", name: "Preview living-note update (no spend)", callback: () => void this.run(true, "manual preview") });
    this.addCommand({ id: "sync-living-note", name: "Sync designated living note now", callback: () => void this.run(false, "manual sync") });

    this.registerEvent(this.app.vault.on("modify", (file) => {
      if (!this.settings.autoSync || !(file instanceof TFile) || file.extension !== "md") return;
      if (file.path === this.settings.targetPath) return; // Never self-trigger on our own output.
      if (!this.isEligibleSource(file.path)) return;
      this.scheduleAutomaticRun();
    }));
    this.registerInterval(window.setInterval(() => void this.tick(), TICK_MS));
  }

  override onunload(): void {
    if (this.debounceTimer) window.clearTimeout(this.debounceTimer);
  }

  async loadSettings(): Promise<void> {
    const saved = await this.loadData() as { settings?: Partial<LivingNoteSettings>; state?: PersistedState } | null;
    this.settings = { ...DEFAULT_SETTINGS, ...(saved?.settings ?? {}) };
    this.state = saved?.state ?? {};
  }

  async saveSettings(): Promise<void> {
    await this.saveData({ settings: this.settings, state: this.state });
  }

  private async setActiveNoteAsTarget(): Promise<void> {
    const file = this.app.workspace.getActiveFile();
    if (!file || file.extension !== "md") {
      new Notice("Open a Markdown note first.");
      return;
    }
    this.settings.targetPath = file.path;
    await this.saveSettings();
    new Notice(`Living note set to ${file.path}`);
  }

  private async initializeOwnedRegion(): Promise<void> {
    const target = await this.targetFile();
    if (!target) return;
    const current = await this.app.vault.read(target);
    const validation = parseOwnership(current);
    if (validation.regions.length > 0 || validation.errors.some((error) => !error.startsWith("no owned regions"))) {
      new Notice("This note already has ownership markers, or a malformed marker pair. No changes made.");
      return;
    }
    const block = [
      "",
      "<!-- superdocs:owned:start id=\"summary\" -->",
      "_Waiting for the first reviewed SuperDocs run. Everything between these two markers is the agent's boundary; everything outside stays yours._",
      "<!-- superdocs:owned:end id=\"summary\" -->",
      "",
    ].join("\n");
    await this.app.vault.append(target, block);
    new Notice("Added an ownership boundary. Add your source notes, then run a no-spend preview.");
  }

  private async targetFile(): Promise<TFile | null> {
    if (!this.settings.targetPath) {
      new Notice("Choose a designated note in Settings, or run 'Set active note as designated living note'.");
      return null;
    }
    const file = this.app.vault.getFileByPath(this.settings.targetPath);
    if (!file || file.extension !== "md") {
      new Notice(`Designated note not found: ${this.settings.targetPath}`);
      return null;
    }
    return file;
  }

  private isEligibleSource(path: string): boolean {
    if (path === this.settings.targetPath || path.startsWith(".obsidian/") || path.startsWith(".trash/")) return false;
    if (this.settings.sourceFolders.length === 0) return true;
    return this.settings.sourceFolders.some((folder) => path === folder || path.startsWith(`${folder.replace(/\/$/, "")}/`));
  }

  private scheduleAutomaticRun(): void {
    if (this.debounceTimer) window.clearTimeout(this.debounceTimer);
    this.debounceTimer = window.setTimeout(() => {
      this.debounceTimer = undefined;
      void this.run(false, "source note changed");
    }, DEBOUNCE_MS);
  }

  /** One tick per minute; the configured interval is honoured without re-registering a timer. */
  private async tick(): Promise<void> {
    if (!this.settings.autoSync || this.settings.previewOnly || this.running || !this.settings.apiKey.trim()) return;
    const due = this.lastScheduledCheck + Math.max(1, this.settings.refreshIntervalMinutes) * 60_000;
    if (Date.now() < due) return;
    this.lastScheduledCheck = Date.now();
    const files = eligibleSourceFiles(this.app, this.settings.targetPath, this.settings.sourceFolders);
    const fingerprint = fingerprintFiles(files.map((file) => ({ path: file.path, mtime: file.stat.mtime, size: file.stat.size })));
    if (!fingerprint.hash) return;
    if (!this.state.lastProcessedSourceFingerprint) {
      // First tick after automatic sync was switched on. Record where the vault
      // stands rather than spending on a change nobody asked us to catch up on.
      this.state.lastProcessedSourceFingerprint = fingerprint.hash;
      await this.saveSettings();
      return;
    }
    if (this.alreadyHandled(fingerprint.hash)) return;
    await this.run(false, "scheduled source check");
  }

  /** A source state is reconciled once, whether that reconciliation succeeded or failed. */
  private alreadyHandled(hash: string): boolean {
    return hash === this.state.lastProcessedSourceFingerprint || hash === this.state.lastAttemptedSourceFingerprint;
  }

  async run(preview: boolean, reason: string): Promise<void> {
    if (this.running) {
      new Notice("A living-note run is already in progress; this run was not queued.");
      return;
    }
    this.running = true;
    this.setStatus(preview ? "preview" : "working");
    let failed = false;
    try {
      const target = await this.targetFile();
      if (!target) return;
      const original = await this.app.vault.read(target);
      const ownership = parseOwnership(original);
      if (ownership.errors.length) throw new Error(ownership.errors.join("; "));

      const plan = await createPreviewPlan(this.app, target.path, this.settings.sourceFolders, ownership.regions, original, this.settings.maxSources);
      if (preview || this.settings.previewOnly) {
        this.showPreview(plan);
        return;
      }
      if (!this.settings.apiKey.trim()) throw new Error("Set a SuperDocs API key in Settings before starting a paid run.");
      if (reason !== "manual sync" && this.alreadyHandled(plan.sourceFingerprint.hash)) return;

      // Recorded before the first paid call: a run that fails afterwards must not
      // be retried automatically, or a deterministic failure bills forever.
      this.state.lastAttemptedSourceFingerprint = plan.sourceFingerprint.hash;
      await this.saveSettings();

      const sessionId = `obsidian-living-${safeHash(`${target.path}:${plan.sourceFingerprint.hash}`)}`;
      const client = new SuperDocsClient(this.settings.baseUrl, this.settings.apiKey.trim());

      // Only owned-region content is uploaded as the editable document; the note
      // itself and the vault sources go up as read-only reference material.
      const document = buildRegionDocument(original, ownership.regions);
      const uploaded = await client.uploadDocument(sessionId, `${target.basename} (owned regions).md`, document.markdown);
      if (!uploaded.html) throw new Error("SuperDocs did not return the parsed document; no edit was started.");
      const chunkIndex = alignChunks(uploaded.html, document.blocks);

      await client.uploadReference(sessionId, `CONTEXT - ${target.name}`, original);
      for (const source of plan.sources) await client.uploadReference(sessionId, source.path.replace(/[\\/]/g, " - "), source.content);
      await client.waitForAttachments(sessionId, plan.sources.length + 1);

      const jobId = await client.startReconciliation({
        sessionId,
        message: [
          ownershipPrompt(ownership.regions),
          `The regions come from the Obsidian note '${target.path}'. Reconcile them once from the attached vault notes.`,
          `Attached reference files: ${["CONTEXT - " + target.name, ...plan.sources.map((source) => source.path)].join(", ")}.`,
          "The CONTEXT attachment is the full note for background only; it is not yours to edit and its text is not part of the document.",
          "Propose targeted edits to the existing paragraphs. Do not restate the sources verbatim, do not add sections that were not asked for, and do not run another reconciliation after this one.",
          "If nothing needs changing, propose no changes and say the note is already current.",
        ].join("\n\n"),
        modelTier: this.settings.modelTier,
        thinkingDepth: this.settings.thinkingDepth,
        crossSessionSearch: this.settings.enableCrossSessionSearch,
        crossSessionMemory: this.settings.enableCrossSessionMemory,
        memoryKey: this.settings.memoryKey || undefined,
      });

      let reviewRounds = 0;
      const approved = new Map<string, PendingChange>();
      const deadline = Date.now() + JOB_DEADLINE_MS;
      let job: JobStatus;
      for (;;) {
        if (Date.now() > deadline) throw new Error("SuperDocs did not finish this reconciliation within 15 minutes; nothing was written. Check the job in SuperDocs before running again.");
        job = await client.getJob(jobId);
        if (job.status === "awaiting_approval") {
          if (job.metadata?.awaiting_kind === "continue_prompt") {
            throw new Error("SuperDocs paused for a large-edit continue prompt. This plugin stops there rather than spending again; open the job in SuperDocs to continue it deliberately.");
          }
          const changes = pendingChanges(job);
          if (!changes.length) throw new Error("SuperDocs reported an approval pause without a pending change list.");
          reviewRounds++;
          if (reviewRounds > MAX_REVIEW_ROUNDS) throw new Error(`The review reached its ${MAX_REVIEW_ROUNDS}-round stopping condition; nothing further was requested.`);
          const decisions = await this.review(changes, reviewRounds, MAX_REVIEW_ROUNDS);
          for (const decision of decisions) {
            const change = changes.find((candidate) => candidate.change_id === decision.change_id);
            if (change && decision.approved) approved.set(change.chunk_id ?? change.change_id, change);
          }
          await client.approveChanges(sessionId, jobId, decisions);
          continue;
        }
        if (["completed", "failed", "cancelled"].includes(job.status)) break;
        await new Promise((resolve) => window.setTimeout(resolve, 1_500));
      }
      if (job.status !== "completed") throw new Error(formatJobError(job));

      const usage = jobUsage(job);
      const cost = usage.ops_charged ? `${usage.ops_charged} operation${usage.ops_charged === 1 ? "" : "s"}` : "no billable operation";
      if (approved.size === 0) {
        this.state.lastProcessedSourceFingerprint = plan.sourceFingerprint.hash;
        await this.saveSettings();
        new Notice(`Living note left unchanged: no proposed change was approved (${cost}).`);
        return;
      }

      const candidate = applyApprovedChanges(original, document, chunkIndex, [...approved.values()]);
      assertExportAgrees(candidate, await client.exportMarkdown(sessionId));

      await this.app.vault.process(target, (current) => {
        if (current !== original) throw new Error("The designated note changed while the review was open; nothing was written. Run the sync again.");
        return candidate;
      });
      this.state.lastProcessedSourceFingerprint = plan.sourceFingerprint.hash;
      this.state.lastSuccessfulRunAt = Date.now();
      await this.saveSettings();
      new Notice(`Living note updated inside its owned regions: ${approved.size} approved change${approved.size === 1 ? "" : "s"} (${cost}).`);
    } catch (error) {
      failed = true;
      showError(error);
    } finally {
      this.running = false;
      this.setStatus(failed ? "error" : "idle");
    }
  }

  private setStatus(status: "idle" | "preview" | "working" | "error"): void {
    if (!this.statusBar) return;
    this.statusBar.setText(`Living note: ${status}`);
    this.statusBar.setAttr("aria-label", "SuperDocs Living Note status");
  }
}

function safeHash(value: string): string {
  let hash = 2166136261;
  for (let i = 0; i < value.length; i++) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16);
}

function formatJobError(job: JobStatus): string {
  if (typeof job.error === "string") return `SuperDocs job ${job.status}: ${job.error}`;
  return `SuperDocs job ${job.status}: ${job.error?.message ?? "no additional error details"}`;
}
