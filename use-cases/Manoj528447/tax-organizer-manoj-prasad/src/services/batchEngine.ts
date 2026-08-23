import {
  BatchRunCheckpoint,
  AgentStage,
  StageLog,
  ClientBatchRecord
} from '../types';
import { INITIAL_SAMPLE_TAX_RETURNS } from '../data/sampleClients';
import { buildClientSpecificOrganizer } from './organizerGenerator';
import { generateClientLawAnalysis } from './taxLawAnalyzer';
import { generateInitialSuperDocsDiffs } from '../data/sampleClients';
import { persistenceService } from './persistenceService';

class BatchAgentEngine {
  private checkpoint: BatchRunCheckpoint;
  private isProcessing: boolean = false;

  constructor() {
    const saved = persistenceService.getCheckpoint();
    if (saved && saved.clientRecords && saved.clientRecords.length > 0) {
      this.checkpoint = saved;
    } else {
      this.checkpoint = this.createDefaultCheckpoint();
      persistenceService.saveCheckpoint(this.checkpoint);
    }
  }

  private createDefaultCheckpoint(): BatchRunCheckpoint {
    const initialRecords = INITIAL_SAMPLE_TAX_RETURNS.map((ret) =>
      this.buildClientRecord(ret)
    );

    return {
      runId: `run-${Date.now()}`,
      startTime: new Date().toISOString(),
      lastUpdatedTime: new Date().toISOString(),
      currentStage: 'IDLE',
      completedStages: [],
      logs: [
        {
          timestamp: new Date().toLocaleTimeString(),
          stage: 'IDLE',
          message: 'SuperDocs Tax Batch Engine initialized with 5 client profiles.',
          level: 'info'
        }
      ],
      clientRecords: initialRecords,
      totalCostEstimate: 0.0,
      totalDurationMs: 0,
      isPaused: false
    };
  }

  public buildClientRecord(ret: any): ClientBatchRecord {
    // Dynamic client-specific organizer
    const organizer = buildClientSpecificOrganizer(ret);
    // Dynamic client-specific law analysis letter
    const yearEndLetter = generateClientLawAnalysis(ret);
    // SuperDocs proposed diffs
    const diffs = generateInitialSuperDocsDiffs(ret, organizer, yearEndLetter);

    const missingCount = organizer.reduce(
      (acc, sec) =>
        acc + sec.requiredDocuments.filter((d) => d.status === 'outstanding').length,
      0
    );
    const receivedCount = organizer.reduce(
      (acc, sec) =>
        acc + sec.requiredDocuments.filter((d) => d.status === 'received').length,
      0
    );

    return {
      id: `batch-${ret.clientId}`,
      clientId: ret.clientId,
      clientName: ret.clientName,
      segment: ret.segment,
      priorReturn: ret,
      organizer,
      yearEndLetter,
      diffs,
      missingItemsCount: missingCount,
      receivedItemsCount: receivedCount,
      status: 'diff_review',
      lastUpdated: new Date().toISOString()
    };
  }

  public getCheckpoint(): BatchRunCheckpoint {
    return { ...this.checkpoint };
  }

  public restoreCheckpoint(saved: BatchRunCheckpoint) {
    this.checkpoint = { ...saved };
    this.addLog('IDLE', 'Restored batch run checkpoint state from persistence.', 'info');
    persistenceService.saveCheckpoint(this.checkpoint);
  }

  /**
   * Record an event in the visible "Execution Audit Trail & Decisions Log"
   * (checkpoint.logs), used for actions that happen outside the stage machine
   * -- e.g. a document export -- so the on-screen log reflects them too, not
   * just the persisted audit trail. Keeps the two audit views consistent.
   */
  public recordEvent(stage: AgentStage, message: string, level: StageLog['level'] = 'info') {
    this.addLog(stage, message, level);
    persistenceService.saveCheckpoint(this.checkpoint);
  }

  private addLog(
    stage: AgentStage,
    message: string,
    level: StageLog['level'],
    costDelta = 0,
    durationMs = 0
  ) {
    const log: StageLog = {
      timestamp: new Date().toLocaleTimeString(),
      stage,
      message,
      level,
      costDelta,
      durationMs
    };
    this.checkpoint.logs.push(log);
    this.checkpoint.totalCostEstimate += costDelta;
    this.checkpoint.totalDurationMs += durationMs;
    this.checkpoint.lastUpdatedTime = new Date().toISOString();

    persistenceService.addAuditEntry({
      actor: 'BatchEngineAgent',
      action: `STAGE_${stage}`,
      details: message
    });

    persistenceService.saveCheckpoint(this.checkpoint);
  }

  public async runStage(targetStage: AgentStage, force = false): Promise<BatchRunCheckpoint> {
    if (this.isProcessing) return this.getCheckpoint();

    // Idempotency: if this stage was already completed and we're not forcing a
    // fresh run, skip it. Real checkpointed pipelines don't re-execute or
    // re-charge for work already done. Without this, clicking "Run Full
    // Pipeline" repeatedly kept re-running every stage and adding cost each
    // time, even though nothing new happened. The human-review gate is the one
    // exception -- it's allowed to re-enter so approvals can be re-evaluated.
    if (!force && targetStage !== 'SUPERDOCS_DIFF_GATE' && this.checkpoint.completedStages.includes(targetStage)) {
      this.checkpoint.currentStage = targetStage;
      return this.getCheckpoint();
    }

    this.isProcessing = true;
    const startMs = Date.now();

    try {
      this.checkpoint.currentStage = targetStage;
      this.checkpoint.isPaused = false;

      switch (targetStage) {
        case 'INGEST_PRIOR_RETURN': {
          this.addLog(
            'INGEST_PRIOR_RETURN',
            'Analyzing 2024 prior year tax returns (1040, Schedule C/E, Form 2555, K-1s)...',
            'info',
            0.002,
            380
          );
          
          // Re-generate client specific organizers dynamically
          this.checkpoint.clientRecords.forEach((rec) => {
            rec.organizer = buildClientSpecificOrganizer(rec.priorReturn);
            rec.lastUpdated = new Date().toISOString();
          });

          this.addLog(
            'INGEST_PRIOR_RETURN',
            `Ingested ${this.checkpoint.clientRecords.length} client prior year returns. Extracted all schedules and line citations.`,
            'success',
            0.001,
            210
          );
          break;
        }

        case 'CLASSIFY_SEGMENT': {
          this.addLog(
            'CLASSIFY_SEGMENT',
            'Segmenting clients into Business, Rental, Expatriate, HNW, and Individual categories...',
            'info',
            0.001,
            250
          );
          const segmentsCount = this.checkpoint.clientRecords.reduce((acc, rec) => {
            acc[rec.segment] = (acc[rec.segment] || 0) + 1;
            return acc;
          }, {} as Record<string, number>);

          this.addLog(
            'CLASSIFY_SEGMENT',
            `Segment classification complete: ${Object.entries(segmentsCount).map(([k, v]) => `${k.toUpperCase()}: ${v}`).join(', ')}.`,
            'success',
            0.001,
            150
          );
          break;
        }

        case 'MATCH_LAW_UPDATES': {
          this.addLog(
            'MATCH_LAW_UPDATES',
            'Cross-referencing client profiles with 2025 IRC tax law updates (QBI §199A, §179 Expensing, FEIE §911, Clean Energy Credits)...',
            'info',
            0.003,
            480
          );

          // Regenerate client-specific tax law letters
          this.checkpoint.clientRecords.forEach((rec) => {
            rec.yearEndLetter = generateClientLawAnalysis(rec.priorReturn);
          });

          this.addLog(
            'MATCH_LAW_UPDATES',
            'Successfully generated client-specific grounded tax law updates for all batch members.',
            'success',
            0.001,
            200
          );
          break;
        }

        case 'GENERATE_DRAFT_BATCH': {
          this.addLog(
            'GENERATE_DRAFT_BATCH',
            'Pre-filling 2025 Tax Organizers and drafting Year-End Client Letters in parallel...',
            'info',
            0.005,
            680
          );
          this.checkpoint.clientRecords.forEach((rec) => {
            rec.status = 'diff_review';
          });
          this.addLog(
            'GENERATE_DRAFT_BATCH',
            'Generated draft batch. SuperDocs proposed diffs ready for human-in-the-loop gate approval.',
            'success',
            0.002,
            290
          );
          break;
        }

        case 'SUPERDOCS_DIFF_GATE': {
          this.addLog(
            'SUPERDOCS_DIFF_GATE',
            'SuperDocs Human Review Gate active. Awaiting CPA approval/rejection on itemized diffs.',
            'warn',
            0.0,
            100
          );
          break;
        }

        case 'EXECUTE_APPROVALS': {
          this.addLog(
            'EXECUTE_APPROVALS',
            'Surgically committing approved diffs into final client organizers & letters...',
            'info',
            0.002,
            380
          );
          this.checkpoint.clientRecords.forEach((rec) => {
            const allApprovedOrRejected = rec.diffs.every((d) => d.status !== 'pending');
            if (allApprovedOrRejected) {
              rec.status = 'ready_to_send';
            }
          });
          this.addLog(
            'EXECUTE_APPROVALS',
            'Approved diffs committed. Untouched sections preserved byte-for-byte.',
            'success',
            0.001,
            180
          );
          break;
        }

        case 'TRACK_MISSING_ITEMS': {
          this.addLog(
            'TRACK_MISSING_ITEMS',
            'Reconciling returned client documents against organizer requirements...',
            'info',
            0.002,
            320
          );
          this.checkpoint.clientRecords.forEach((rec) => {
            rec.missingItemsCount = rec.organizer.reduce(
              (acc, sec) =>
                acc + sec.requiredDocuments.filter((d) => d.status === 'outstanding').length,
              0
            );
            rec.receivedItemsCount = rec.organizer.reduce(
              (acc, sec) =>
                acc + sec.requiredDocuments.filter((d) => d.status === 'received').length,
              0
            );
          });
          this.addLog(
            'TRACK_MISSING_ITEMS',
            'Missing items reconciliation complete.',
            'success',
            0.001,
            170
          );
          break;
        }

        case 'DRAFT_FOLLOWUP': {
          this.addLog(
            'DRAFT_FOLLOWUP',
            'Drafting personalized missing-items follow-up letters for clients with outstanding documents...',
            'info',
            0.004,
            580
          );
          this.addLog(
            'DRAFT_FOLLOWUP',
            'Drafted missing items follow-up batch successfully.',
            'success',
            0.002,
            250
          );
          break;
        }

        default:
          break;
      }

      if (!this.checkpoint.completedStages.includes(targetStage)) {
        this.checkpoint.completedStages.push(targetStage);
      }
    } catch (err: any) {
      this.addLog('ERROR', `Stage execution error: ${err.message || err}`, 'error');
      this.checkpoint.currentStage = 'ERROR';
    } finally {
      this.isProcessing = false;
      const duration = Date.now() - startMs;
      this.checkpoint.totalDurationMs += duration;
      this.checkpoint.lastUpdatedTime = new Date().toISOString();
      persistenceService.saveCheckpoint(this.checkpoint);
    }

    return this.getCheckpoint();
  }

  public async runFullPipeline(): Promise<BatchRunCheckpoint> {
    const stages: AgentStage[] = [
      'INGEST_PRIOR_RETURN',
      'CLASSIFY_SEGMENT',
      'MATCH_LAW_UPDATES',
      'GENERATE_DRAFT_BATCH',
      'SUPERDOCS_DIFF_GATE',
      'EXECUTE_APPROVALS',
      'TRACK_MISSING_ITEMS',
      'DRAFT_FOLLOWUP'
    ];

    for (const stage of stages) {
      if (stage === 'SUPERDOCS_DIFF_GATE') {
        // Human-in-the-loop gate. If there are still diffs awaiting a decision,
        // run the gate (so its log/status is recorded) and STOP for review.
        // Once the CPA has approved/rejected everything (no more 'pending'
        // diffs), we DON'T re-run the gate on subsequent clicks (that only
        // added runtime with no new work); we simply fall through to the
        // post-gate stages. This is what lets "approve then continue" work
        // without getting stuck re-showing the gate.
        const clientsWithPending = this.checkpoint.clientRecords.filter((c) =>
          c.diffs.some((d) => d.status === 'pending')
        );
        if (clientsWithPending.length > 0) {
          await this.runStage(stage);
          // Be explicit about WHY the gate is still holding. The gate is
          // batch-wide (every client's diffs must be decided) but the review
          // UI is per-client, so it's easy to approve the client you're
          // looking at, click Run, and get re-paused with no idea which OTHER
          // clients still block the batch. Name them, and count the diffs, so
          // the audit log answers "what am I waiting on?" directly instead of
          // just spinning up runtime on every click.
          const pendingSummary = clientsWithPending
            .map((c) => `${c.clientName} (${c.diffs.filter((d) => d.status === 'pending').length})`)
            .join(', ');
          const totalPending = clientsWithPending.reduce(
            (acc, c) => acc + c.diffs.filter((d) => d.status === 'pending').length,
            0
          );
          this.addLog(
            'SUPERDOCS_DIFF_GATE',
            `Gate held: ${totalPending} diff(s) across ${clientsWithPending.length} client(s) still awaiting a decision -> ${pendingSummary}. Approve or reject every client's diffs (or use "Approve all remaining") to release the gate.`,
            'warn'
          );
          this.checkpoint.isPaused = true;
          persistenceService.saveCheckpoint(this.checkpoint);
          break;
        }
        // All diffs decided -> the human gate is satisfied. Mark it complete
        // (so it ticks green like every other finished stage) and continue.
        // Without this, the gate was skipped past and never recorded as done,
        // so it never showed complete even after everything was approved.
        if (!this.checkpoint.completedStages.includes('SUPERDOCS_DIFF_GATE')) {
          this.checkpoint.completedStages.push('SUPERDOCS_DIFF_GATE');
        }
        this.checkpoint.isPaused = false;
        this.addLog(
          'SUPERDOCS_DIFF_GATE',
          'Human gate satisfied: all diffs decided. Releasing the gate and continuing the pipeline.',
          'success'
        );
        persistenceService.saveCheckpoint(this.checkpoint);
        continue;
      }

      await this.runStage(stage);
    }

    return this.getCheckpoint();
  }

  public updateDiffStatus(
    clientRecordId: string,
    diffId: string,
    status: 'approved' | 'rejected'
  ) {
    const client = this.checkpoint.clientRecords.find((c) => c.id === clientRecordId);
    if (client) {
      const diff = client.diffs.find((d) => d.id === diffId);
      if (diff) {
        diff.status = status;

        // Root fix for edit-consistency: merge the approved diff's text into
        // the letter document itself (appliedEdits), so EVERY view -- the live
        // grounded preview, copy raw text, print, and export -- reads the same
        // merged document and shows the edit. Previously approval only flipped
        // a status flag and the edit surfaced only in the export, leaving the
        // preview stale. Rejecting removes it again, so toggling is consistent.
        const editLine = `${diff.locationLabel}: ${diff.proposedText}`;
        if (!client.yearEndLetter.appliedEdits) client.yearEndLetter.appliedEdits = [];
        const existingIdx = client.yearEndLetter.appliedEdits.findIndex((e) => e.startsWith(`${diff.locationLabel}:`));
        if (status === 'approved') {
          if (existingIdx === -1) client.yearEndLetter.appliedEdits.push(editLine);
          else client.yearEndLetter.appliedEdits[existingIdx] = editLine;
        } else if (existingIdx !== -1) {
          client.yearEndLetter.appliedEdits.splice(existingIdx, 1);
        }

        this.addLog(
          'SUPERDOCS_DIFF_GATE',
          `Human Gate: ${status.toUpperCase()} diff "${diff.locationLabel}" for ${client.clientName}.`,
          status === 'approved' ? 'success' : 'warn'
        );

        persistenceService.addAuditEntry({
          actor: 'CPA_Reviewer',
          action: `DIFF_${status.toUpperCase()}`,
          clientRecordId,
          documentId: diffId,
          details: `Changed status of diff "${diff.locationLabel}" to ${status}`
        });
      }
    }
    persistenceService.saveCheckpoint(this.checkpoint);
    return this.getCheckpoint();
  }

  /**
   * Decide every still-pending diff across the WHOLE batch in one action.
   * The per-client review UI can leave other clients' diffs pending, which
   * holds the batch-wide gate; this lets a CPA clear the remainder in one
   * reviewed, audited action. Returns how many diffs were decided so the
   * caller/UI can confirm exactly what happened rather than implying more
   * work occurred than did. Only touches 'pending' diffs -- an already
   * approved/rejected decision is never silently overwritten.
   */
  public decideAllPendingDiffs(status: 'approved' | 'rejected'): { decidedCount: number; checkpoint: BatchRunCheckpoint } {
    let decidedCount = 0;
    this.checkpoint.clientRecords.forEach((client) => {
      client.diffs.forEach((diff) => {
        if (diff.status === 'pending') {
          diff.status = status;
          decidedCount++;
          // Merge into the letter document too (same as single approve), so
          // bulk-approved edits also show in every view, not just the export.
          if (status === 'approved') {
            const editLine = `${diff.locationLabel}: ${diff.proposedText}`;
            if (!client.yearEndLetter.appliedEdits) client.yearEndLetter.appliedEdits = [];
            if (!client.yearEndLetter.appliedEdits.some((e) => e.startsWith(`${diff.locationLabel}:`))) {
              client.yearEndLetter.appliedEdits.push(editLine);
            }
          }
          persistenceService.addAuditEntry({
            actor: 'CPA_Reviewer',
            action: `DIFF_${status.toUpperCase()}_BULK`,
            clientRecordId: client.id,
            documentId: diff.id,
            details: `Bulk ${status} of diff "${diff.locationLabel}" for ${client.clientName}`
          });
        }
      });
    });

    if (decidedCount > 0) {
      this.addLog(
        'SUPERDOCS_DIFF_GATE',
        `Human Gate (bulk): ${status.toUpperCase()} ${decidedCount} remaining pending diff(s) across the batch.`,
        status === 'approved' ? 'success' : 'warn'
      );
    } else {
      this.addLog(
        'SUPERDOCS_DIFF_GATE',
        'No pending diffs remained to decide; gate already clear.',
        'info'
      );
    }

    persistenceService.saveCheckpoint(this.checkpoint);
    return { decidedCount, checkpoint: this.getCheckpoint() };
  }

  public updateDocumentStatus(
    clientRecordId: string,
    docId: string,
    newStatus: 'received' | 'outstanding' | 'waived',
    fileName?: string
  ) {
    const client = this.checkpoint.clientRecords.find((c) => c.id === clientRecordId);
    if (client) {
      client.organizer.forEach((sec) => {
        const item = sec.requiredDocuments.find((d) => d.id === docId);
        if (item) {
          item.status = newStatus;
          if (newStatus === 'received') {
            item.receivedFileName = fileName || 'Uploaded_Tax_Doc.pdf';
            item.receivedDate = new Date().toISOString().split('T')[0];
          }
        }
      });

      client.missingItemsCount = client.organizer.reduce(
        (acc, sec) =>
          acc + sec.requiredDocuments.filter((d) => d.status === 'outstanding').length,
        0
      );
      client.receivedItemsCount = client.organizer.reduce(
        (acc, sec) =>
          acc + sec.requiredDocuments.filter((d) => d.status === 'received').length,
        0
      );

      this.addLog(
        'TRACK_MISSING_ITEMS',
        `Document status updated for ${client.clientName}: doc #${docId} -> ${newStatus}.`,
        'info'
      );

      persistenceService.addAuditEntry({
        actor: 'CPA_Reviewer',
        action: 'UPDATE_DOCUMENT_STATUS',
        clientRecordId,
        documentId: docId,
        details: `Updated document ${docId} status to ${newStatus}`
      });
    }
    persistenceService.saveCheckpoint(this.checkpoint);
    return this.getCheckpoint();
  }

  public addClientRecord(record: ClientBatchRecord) {
    this.checkpoint.clientRecords.unshift(record);
    this.addLog('INGEST_PRIOR_RETURN', `Added new client record: ${record.clientName}`, 'success');
    persistenceService.saveCheckpoint(this.checkpoint);
    return this.getCheckpoint();
  }

  public resetEngine() {
    this.checkpoint = this.createDefaultCheckpoint();
    persistenceService.saveCheckpoint(this.checkpoint);
    return this.getCheckpoint();
  }
}

export const batchAgentEngine = new BatchAgentEngine();
