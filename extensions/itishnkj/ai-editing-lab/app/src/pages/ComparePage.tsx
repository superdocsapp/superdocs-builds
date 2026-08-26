import { useMemo, useState } from 'react';
import {
  useCancelReview,
  useGenerateEdit,
  useGetLabConfig,
  type EditResult,
} from '@workspace/api-client-react';
import {
  AlertTriangle,
  Clock,
  FileText,
  GitCompare,
  Loader2,
  Play,
  Upload,
} from 'lucide-react';
import { v4 as uuidv4 } from 'uuid';
import { format } from 'date-fns';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import {
  evaluateFormatting,
  stableDocumentHash,
} from '@/lib/experiment';
import {
  documentSessionTitle,
  telemetryMetadataForDocument,
  type CompareRun,
  type ReviewerScore,
  useLabStore,
} from '@/lib/store';
import {
  applyEditResult,
  estimateRequestContext,
  makeRequestFingerprint,
} from '@/lib/telemetry';
import {
  buildEditRequest,
  contextLimitAction,
  createTelemetryDraftForRequest,
} from '@/lib/telemetry-workflows';
import { usePreferences } from '@/lib/preferences';
import { importDocument } from '@/lib/import/importDocument';
import { DocumentImportError } from '@/lib/import/types';

const EMPTY_REVIEW: ReviewerScore = {
  instructionAdherence: 0,
  writingQuality: 0,
  formattingPreservation: 0,
  overallUsefulness: 0,
  notes: '',
};

function errorMessage(error: unknown) {
  if (error && typeof error === 'object' && 'data' in error) {
    const data = (error as { data?: { error?: string } }).data;
    if (data?.error) return data.error;
  }
  return error instanceof Error ? error.message : 'Request failed';
}

function StepBadge({ step }: { step: number }) {
  return (
    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
      {step}
    </span>
  );
}

function ScoreControl({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:justify-between">
      <span className="text-xs text-muted-foreground">{label}</span>
      <div className="grid grid-cols-5 gap-1" role="radiogroup" aria-label={label}>
        {[1, 2, 3, 4, 5].map((score) => (
          <button
            type="button"
            key={score}
            onClick={() => onChange(score)}
            aria-label={`${label}: ${score} of 5`}
            aria-checked={value === score}
            role="radio"
            className={`h-8 w-8 rounded-md border text-xs font-medium transition ${
              value === score
                ? 'border-primary bg-primary text-primary-foreground'
                : 'bg-background text-muted-foreground hover:border-primary/40'
            }`}
          >
            {score}
          </button>
        ))}
      </div>
    </div>
  );
}

function ResultPanel({
  title,
  result,
  error,
  snapshot,
  review,
  onReview,
  onCancelHostedReview,
  cancellingHostedReview,
}: {
  title: string;
  result: EditResult | null;
  error: string | null;
  snapshot: string;
  review: ReviewerScore;
  onReview: (review: ReviewerScore) => void;
  onCancelHostedReview?: () => void;
  cancellingHostedReview?: boolean;
}) {
  const candidate = result?.candidateDocumentHtml ?? null;
  const hostedProposal =
    result?.review != null && result.proposedChanges.length > 0;
  const formatting = evaluateFormatting(
    snapshot,
    candidate,
    ['headings', 'bold', 'italic', 'links', 'lists', 'blockquotes', 'tables'],
  );
  return (
    <Card className="flex min-w-0 max-w-full flex-col overflow-hidden">
      <div className="flex items-start justify-between gap-2 border-b bg-muted/20 p-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">{title}</h2>
          <p className="text-[11px] text-muted-foreground">
            {result
              ? `${hostedProposal ? 'Review proposal ready' : 'Responded'} in ${((result.latencyMs ?? 0) / 1000).toFixed(1)}s${result.retryCount ? ` · ${result.retryCount} retries` : ''}`
              : 'No successful proposal'}
          </p>
        </div>
        <Badge
          variant="outline"
            className={`shrink-0 ${
            formatting.status === 'PASS'
              ? 'border-emerald-500/30 text-emerald-700 dark:text-emerald-400'
              : formatting.status === 'N/A'
                ? ''
                : 'border-amber-500/30 text-amber-700 dark:text-amber-400'
          }`}
        >
          Formatting {formatting.status}
        </Badge>
      </div>

      <div className="min-w-0 space-y-4 p-4">
        {candidate ? (
          <div className="max-h-80 max-w-full overflow-auto rounded-md border bg-background">
            <div
              className="prose prose-sm min-w-0 max-w-none break-words p-4 [overflow-wrap:anywhere] dark:prose-invert [&_*]:max-w-full [&_table]:table-fixed [&_table]:w-full"
              dangerouslySetInnerHTML={{ __html: candidate }}
            />
          </div>
        ) : hostedProposal ? (
          <div className="max-h-80 max-w-full overflow-y-auto overscroll-contain rounded-md border border-primary/25 bg-primary/5">
            <div className="p-4">
              <p className="text-sm font-medium">Hosted review proposal ready</p>
              <p className="mt-1 text-xs text-muted-foreground">
                SuperDocs returned {result.proposedChanges.length} proposed{' '}
                {result.proposedChanges.length === 1 ? 'change' : 'changes'} for
                review. Its hosted workflow keeps those changes pending instead
                of returning a complete replacement document, so the structured
                before-and-after details appear below.
              </p>
            </div>
            <div className="border-t border-primary/20 p-3 text-xs">
              <p className="font-semibold">
                Hosted review batch {result?.review?.batchNumber}
              </p>
              <p className="mt-1 text-muted-foreground">
                Comparison runs retain the provider’s proposed chunks without
                approving or applying them to your document.
              </p>
              <div className="mt-2 space-y-2">
                {result.proposedChanges.map((change) => (
                  <div key={change.id} className="rounded border bg-background p-2">
                    <p className="font-medium">{change.chunkId ?? change.target ?? 'Document chunk'}</p>
                    <p className="mt-1 text-muted-foreground">{change.explanation ?? 'No provider explanation returned.'}</p>
                    {(change.oldHtml || change.newHtml) && (
                      <div className="mt-2 grid gap-2">
                        {change.oldHtml && (
                          <div>
                            <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                              Before
                            </p>
                            <div className="max-w-full overflow-x-auto rounded border bg-muted/20">
                              <div
                                className="prose prose-xs min-w-0 max-w-none break-words p-2 [overflow-wrap:anywhere] dark:prose-invert [&_*]:max-w-full [&_table]:table-fixed [&_table]:w-full"
                                dangerouslySetInnerHTML={{ __html: change.oldHtml }}
                              />
                            </div>
                          </div>
                        )}
                        {change.newHtml && (
                          <div>
                            <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-primary">
                              Proposed
                            </p>
                            <div className="max-w-full overflow-x-auto rounded border border-primary/25 bg-primary/5">
                              <div
                                className="prose prose-xs min-w-0 max-w-none break-words p-2 [overflow-wrap:anywhere] dark:prose-invert [&_*]:max-w-full [&_table]:table-fixed [&_table]:w-full"
                                dangerouslySetInnerHTML={{ __html: change.newHtml }}
                              />
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-4 text-sm">
            <div className="mb-2 flex items-center font-medium text-amber-700 dark:text-amber-400">
              <AlertTriangle className="mr-2 h-4 w-4" />
              No proposal available
            </div>
            <p className="text-xs text-muted-foreground">
              {error ?? 'The engine did not return a candidate document.'}
            </p>
          </div>
        )}
        {hostedProposal && onCancelHostedReview && (
          <Button
            className="h-10 w-full"
            variant="outline"
            size="sm"
            onClick={onCancelHostedReview}
            disabled={cancellingHostedReview}
            data-testid="button-cancel-hosted-compare"
          >
            Cancel hosted review
          </Button>
        )}

        <dl className="grid grid-cols-2 gap-2 rounded-md border p-3 text-xs">
          <dt className="text-muted-foreground">Input tokens</dt>
          <dd className="text-right font-mono">
            {result?.usage?.inputTokens ?? 'Not exposed'}
          </dd>
          <dt className="text-muted-foreground">Output tokens</dt>
          <dd className="text-right font-mono">
            {result?.usage?.outputTokens ?? 'Not exposed'}
          </dd>
          <dt className="text-muted-foreground">Hosted response data</dt>
          <dd className="truncate text-right font-mono">
            {result?.usage?.hostedUsage ?? 'Not exposed'}
          </dd>
          <dt className="text-muted-foreground">Formatting detail</dt>
          <dd className="col-span-2 text-muted-foreground">
            {formatting.detail}
          </dd>
        </dl>
      </div>
      <div className="border-t bg-muted/10 p-4">
        <div className="mb-3 flex items-center justify-between gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider">Your score</h3>
          <span className="text-[10px] text-muted-foreground">Saved automatically</span>
        </div>
        <div className="space-y-3">
          <ScoreControl
            label="Instruction adherence"
            value={review.instructionAdherence}
            onChange={(instructionAdherence) =>
              onReview({ ...review, instructionAdherence })
            }
          />
          <ScoreControl
            label="Writing quality"
            value={review.writingQuality}
            onChange={(writingQuality) =>
              onReview({ ...review, writingQuality })
            }
          />
          <ScoreControl
            label="Formatting preservation"
            value={review.formattingPreservation}
            onChange={(formattingPreservation) =>
              onReview({ ...review, formattingPreservation })
            }
          />
          <ScoreControl
            label="Overall usefulness"
            value={review.overallUsefulness}
            onChange={(overallUsefulness) =>
              onReview({ ...review, overallUsefulness })
            }
          />
          <Textarea
            value={review.notes}
            onChange={(event) =>
              onReview({ ...review, notes: event.target.value })
            }
            placeholder="Your notes…"
            className="min-h-20 resize-none text-xs"
          />
        </div>
      </div>
    </Card>
  );
}

export default function ComparePage() {
  const {
    currentDocumentHtml,
    documentSession,
    versions,
    compareRuns,
    benchmarkRuns,
    addCompareRun,
    updateCompareRun,
    startImportedDocument,
    logActivity,
    setLatestResults,
    telemetry,
    observabilitySettings,
    recordTelemetry,
    updateTelemetryForRequest,
  } = useLabStore();
  const { preferences } = usePreferences();
  const { data: config } = useGetLabConfig();
  const generateEdit = useGenerateEdit();
  const cancelReview = useCancelReview();
  const [instruction, setInstruction] = useState(
    'Make the executive summary more concise without changing unrelated content.',
  );
  const [isRunning, setIsRunning] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [isCancellingReview, setIsCancellingReview] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(
    compareRuns[0]?.id ?? null,
  );

  const bothConfigured = useMemo(
    () =>
      Boolean(
        config?.engines.find((engine) => engine.id === 'diy')?.configured &&
          config?.engines.find((engine) => engine.id === 'superdocs')
            ?.configured,
      ),
    [config],
  );
  const selectedRun = compareRuns.find((run) => run.id === selectedRunId);
  const engineStatuses = useMemo(
    () => new Map(config?.engines.map((engine) => [engine.id, engine]) ?? []),
    [config],
  );
  const contextPreflight = useMemo(
    () =>
      estimateRequestContext({
        engine: 'superdocs',
        documentHtml: currentDocumentHtml,
        scope: 'document',
        instruction: instruction.trim(),
        contextBudgetChars: observabilitySettings.contextBudgetChars,
        softContextBudgetChars: observabilitySettings.softContextBudgetChars,
      }),
    [currentDocumentHtml, instruction, observabilitySettings],
  );

  const canReplaceDocument = () => {
    if (compareRuns.some((run) => run.superdocsResult?.review)) {
      toast.error(
        'Cancel the pending hosted review in the current comparison before replacing the document.',
      );
      return false;
    }
    const wouldClearSession =
      documentSession.sourceType === 'imported' ||
      versions.length > 1 ||
      compareRuns.length > 0 ||
      benchmarkRuns.length > 0;
    if (
      (currentDocumentHtml !== documentSession.originalHtml || wouldClearSession) &&
      !window.confirm(
        'Replace this document? This starts a new document session and clears the current version history, comparisons, and benchmarks. Your chat and edit history stay available in History.',
      )
    ) {
      return false;
    }
    return true;
  };

  const handleImportFile = async (file: File | null) => {
    if (!file || isImporting || isRunning || !canReplaceDocument()) return;
    setIsImporting(true);
    try {
      const imported = await importDocument(file);
      startImportedDocument(imported);
      setSelectedRunId(null);
      toast.success(`Imported ${imported.originalFileName}.`);
    } catch (error) {
      toast.error(
        error instanceof DocumentImportError
          ? error.message
          : 'This document could not be parsed. Try a DOCX, PDF, HTML, or TXT file.',
      );
    } finally {
      setIsImporting(false);
    }
  };

  const handleRunCompare = async () => {
    if (!instruction.trim() || !bothConfigured) return;
    if (contextLimitAction(contextPreflight) === 'block') {
      toast.error(
        `This comparison would send ${contextPreflight.contextChars.toLocaleString()} context characters, above the configured application limit.`,
      );
      return;
    }
    if (
      contextLimitAction(contextPreflight) === 'confirm' &&
      !window.confirm(
        `This comparison will send ${contextPreflight.contextChars.toLocaleString()} context characters, above the soft budget. Continue without reducing the source document?`,
      )
    ) {
      return;
    }
    setIsRunning(true);
    try {
    const frozenHtml = currentDocumentHtml;
    const startingVersionId = versions[0]?.id ?? uuidv4();
    const requestId = uuidv4();
    const baseInput = {
      documentHtml: frozenHtml,
      scope: 'document' as const,
      instruction: instruction.trim(),
      requestId,
      currentVersionId: startingVersionId,
    };
    const comparisonFingerprints = await Promise.all(
      (['diy', 'superdocs'] as const).map(async (engine) => ({
        engine,
        fingerprint: await makeRequestFingerprint({
            engine,
            documentHtml: frozenHtml,
            scope: 'document',
            instruction: instruction.trim(),
        }),
      })),
    );
    const duplicateCount = comparisonFingerprints.filter(({ fingerprint }) =>
      telemetry.some((record) => record.requestFingerprint === fingerprint),
    ).length;
    if (
      duplicateCount &&
      !window.confirm(
        'This exact controlled comparison has already been recorded. Running it again creates fresh provider calls and does not reuse a prior proposal. Continue?',
      )
    ) {
      return;
    }

    const requestRecords = new Map();
    const requests = new Map(
      (['diy', 'superdocs'] as const).map((engine) => [
        engine,
        buildEditRequest({ ...baseInput, engine, preset: null }),
      ]),
    );
    const startedAt = performance.now();
    await Promise.all((['diy', 'superdocs'] as const).map(async (engine) => {
      const fingerprint = comparisonFingerprints.find(
        (candidate) => candidate.engine === engine,
      )?.fingerprint;
      const prior = telemetry.find(
        (record) =>
          record.requestFingerprint === fingerprint,
      );
      const request = requests.get(engine);
      if (!request) throw new Error(`Missing ${engine} comparison request.`);
      const record = recordTelemetry({
        ...(await createTelemetryDraftForRequest({
          request,
          modelLabel: engineStatuses.get(engine)?.modelLabel ?? 'Not configured',
          settings: observabilitySettings,
          documentMetadata: telemetryMetadataForDocument(
            documentSession,
            frozenHtml,
          ),
        })),
        duplicateOf: prior?.id ?? null,
      });
      requestRecords.set(engine, record);
    }));

    const [diy, superdocs] = await Promise.allSettled([
      generateEdit.mutateAsync({ data: requests.get('diy')! }),
      generateEdit.mutateAsync({ data: requests.get('superdocs')! }),
    ]);
    const diyResult = diy.status === 'fulfilled' ? diy.value : null;
    const superdocsResult =
      superdocs.status === 'fulfilled' ? superdocs.value : null;
    (
      [
        ['diy', diy],
        ['superdocs', superdocs],
      ] as const
    ).forEach(([engine, response]) => {
      const record = requestRecords.get(engine);
      if (response.status === 'fulfilled' && record) {
        updateTelemetryForRequest(
          requestId,
          engine,
          applyEditResult(record, response.value),
        );
      } else if (response.status === 'rejected') {
        updateTelemetryForRequest(requestId, engine, {
          outcome: 'error',
          error: errorMessage(response.reason),
          latencyMs: Math.round(performance.now() - startedAt),
          retryCount: null,
        });
      }
    });
    const created = addCompareRun({
      snapshotHtml: frozenHtml,
      startingDocumentHash: stableDocumentHash(frozenHtml),
      startingVersionId,
      instruction: instruction.trim(),
      scope: 'document',
      diyResult,
      superdocsResult,
      diyError: diy.status === 'rejected' ? errorMessage(diy.reason) : null,
      superdocsError:
        superdocs.status === 'rejected'
          ? errorMessage(superdocs.reason)
          : null,
      diyReview: { ...EMPTY_REVIEW },
      superdocsReview: { ...EMPTY_REVIEW },
    });
    (['diy', 'superdocs'] as const).forEach((engine) => {
      updateTelemetryForRequest(requestId, engine, {
        compareRunId: created.id,
        decisionState: 'not_applicable',
      });
    });
    setLatestResults(
      [diyResult, superdocsResult].filter(Boolean) as EditResult[],
    );
    setSelectedRunId(created.id);
    logActivity('Controlled comparison recorded', instruction.trim(), {
      engine: 'both',
      scope: 'document',
      requestId,
      status: diyResult || superdocsResult ? 'success' : 'error',
    });
    setInstruction('');
    if (diyResult && superdocsResult) {
      toast.success('Comparison finished — results are below.');
    } else if (diyResult || superdocsResult) {
      toast.warning(
        'Comparison completed with one engine unavailable. Review the error in its result panel.',
      );
    } else {
      toast.error('Neither engine could complete the comparison. Review the errors below.');
    }
    } catch (error) {
      toast.error(`Comparison could not start: ${errorMessage(error)}`);
    } finally {
      setIsRunning(false);
    }
  };

  const updateReview = (
    run: CompareRun,
    key: 'diyReview' | 'superdocsReview',
    review: ReviewerScore,
  ) => {
    updateCompareRun(run.id, { [key]: review });
  };

  const cancelCompareReview = async (run: CompareRun) => {
    const hostedResult = run.superdocsResult;
    const review = hostedResult?.review;
    if (!review) return;
    setIsCancellingReview(true);
    try {
      await cancelReview.mutateAsync({ data: { reviewId: review.reviewId } });
      updateCompareRun(run.id, {
        superdocsResult: null,
        superdocsError:
          'Hosted review cancelled after its proposal was recorded; no provider change was applied.',
      });
      updateTelemetryForRequest(
        hostedResult.requestId,
        'superdocs',
        { outcome: 'cancelled', decisionState: 'stopped' },
      );
      toast.info('Hosted comparison review cancelled; no provider change was applied.');
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setIsCancellingReview(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-[2200px] space-y-6 p-4 md:p-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Compare</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Send the same instruction to both engines at the same time, on the
          same frozen document, and judge the results side by side. Comparisons
          never change your document.
        </p>
      </header>

      <Card>
        <CardContent className="p-4 md:p-6">
          <ol className="grid gap-6 md:grid-cols-3">
            <li className="flex gap-3">
              <StepBadge step={1} />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">Your document</p>
                <div className="mt-2 flex items-center gap-2 rounded-md border bg-muted/20 p-2.5">
                  <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <span className="truncate text-sm" data-testid="text-compare-document">
                    {documentSessionTitle(documentSession)}
                  </span>
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  The entire current document is used, frozen at the moment you
                  run the comparison.
                </p>
                <div className="mt-4 space-y-2">
                  <label htmlFor="compare-upload" className="flex items-center gap-1.5 text-xs font-medium">
                    <Upload className="h-3.5 w-3.5 text-muted-foreground" />
                    Upload a document for this comparison
                  </label>
                  <Input
                    id="compare-upload"
                    type="file"
                    accept=".docx,.pdf,.html,.htm,.txt"
                    disabled={isRunning || isImporting}
                    onChange={(event) => {
                      void handleImportFile(event.target.files?.[0] ?? null);
                      event.currentTarget.value = '';
                    }}
                    className="h-9 text-xs file:mr-2 file:border-0 file:bg-transparent file:text-xs file:font-medium"
                    data-testid="input-compare-upload"
                  />
                  <p className="text-[10px] leading-relaxed text-muted-foreground">
                    DOCX, PDF, HTML, and TXT are supported. Uploading starts a
                    fresh document session and clears earlier comparisons.
                  </p>
                </div>
              </div>
            </li>
            <li className="flex gap-3">
              <StepBadge step={2} />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">The instruction</p>
                <Textarea
                  value={instruction}
                  onChange={(event) => setInstruction(event.target.value)}
                  placeholder="What should both engines do? e.g. “Make the summary more concise.”"
                  className="mt-2 min-h-24 resize-none text-sm"
                  disabled={isRunning}
                  data-testid="input-compare-instruction"
                />
              </div>
            </li>
            <li className="flex gap-3">
              <StepBadge step={3} />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">Run both engines</p>
                <p className="mt-2 text-xs text-muted-foreground">
                  DIY and SuperDocs receive exactly the same input, so the
                  results are a fair head-to-head.
                </p>
                {!bothConfigured && (
                  <p className="mt-2 rounded border border-amber-500/30 bg-amber-500/5 p-2 text-[11px] text-muted-foreground">
                    Comparing needs both engines to be set up. Check System
                    Status in the sidebar for what’s missing.
                  </p>
                )}
                <Button
                  className="mt-3 w-full"
                  onClick={handleRunCompare}
                  disabled={isRunning || !instruction.trim() || !bothConfigured}
                  data-testid="button-run-both"
                >
                  {isRunning ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Play className="mr-2 h-4 w-4" />
                  )}
                  {isRunning ? 'Running both engines…' : 'Run both engines'}
                </Button>
              </div>
            </li>
          </ol>
        </CardContent>
      </Card>

      {compareRuns.length > 0 && (
        <section>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Previous comparisons
          </p>
          <div className="flex max-h-44 flex-col gap-1 overflow-y-auto rounded-md border bg-muted/10 p-2">
            {compareRuns.map((run) => (
              <button
                type="button"
                key={run.id}
                onClick={() => setSelectedRunId(run.id)}
                className={`w-full rounded-md border p-2.5 text-left text-sm transition ${
                  selectedRunId === run.id
                    ? 'border-primary/30 bg-primary/5'
                    : 'border-transparent bg-card hover:border-border'
                }`}
                data-testid={`row-compare-run-${run.id}`}
              >
                <p className="line-clamp-1 font-medium">{run.instruction}</p>
                <p className="mt-0.5 flex items-center text-[10px] text-muted-foreground">
                  <Clock className="mr-1 h-3 w-3" />
                  {format(new Date(run.timestamp), 'MMM d, h:mm a')}
                  {preferences.developerMode && (
                    <span className="ml-2 font-mono">{run.startingDocumentHash}</span>
                  )}
                </p>
              </button>
            ))}
          </div>
        </section>
      )}

      {selectedRun ? (
        <section className="space-y-3" data-testid="section-compare-results">
          <div className="rounded-md border bg-card px-4 py-3">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
              Instruction both engines received
            </p>
            <p className="text-sm font-medium">{selectedRun.instruction}</p>
            {preferences.developerMode && (
              <p className="mt-1 font-mono text-[10px] text-muted-foreground">
                Version {selectedRun.startingVersionId} ·{' '}
                {selectedRun.startingDocumentHash}
              </p>
            )}
          </div>
          <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-3">
            <Card className="min-w-0">
              <div className="border-b bg-muted/20 p-3">
                <h2 className="text-sm font-semibold">Original</h2>
                <p className="text-[11px] text-muted-foreground">
                  The frozen document both engines started from
                </p>
              </div>
              <div className="p-4">
                <div
                  className="prose prose-sm max-h-96 max-w-none overflow-y-auto rounded-md border bg-background p-4 dark:prose-invert"
                  dangerouslySetInnerHTML={{ __html: selectedRun.snapshotHtml }}
                />
              </div>
            </Card>
            <ResultPanel
              title="DIY Toolkit"
              result={selectedRun.diyResult}
              error={selectedRun.diyError}
              snapshot={selectedRun.snapshotHtml}
              review={selectedRun.diyReview}
              onReview={(review) =>
                updateReview(selectedRun, 'diyReview', review)
              }
            />
            <ResultPanel
              title="SuperDocs hosted"
              result={selectedRun.superdocsResult}
              error={selectedRun.superdocsError}
              snapshot={selectedRun.snapshotHtml}
              review={selectedRun.superdocsReview}
              onReview={(review) =>
                updateReview(selectedRun, 'superdocsReview', review)
              }
              onCancelHostedReview={() => void cancelCompareReview(selectedRun)}
              cancellingHostedReview={isCancellingReview}
            />
          </div>
        </section>
      ) : (
        <div className="flex flex-col items-center rounded-lg border border-dashed py-16 text-center">
          <GitCompare className="h-8 w-8 text-muted-foreground" />
          <p className="mt-3 text-sm font-medium">No comparisons yet</p>
          <p className="mt-1 max-w-sm text-xs text-muted-foreground">
            Write an instruction above and run both engines — you’ll see the
            original document, the DIY result, and the SuperDocs result side by
            side, ready to score.
          </p>
        </div>
      )}
    </div>
  );
}
