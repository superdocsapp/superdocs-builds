import { useMemo, useRef, useState } from 'react';
import {
  useCancelReview,
  useGenerateEdit,
  useGetLabConfig,
  type EditInputEngine,
  type EditResult,
} from '@workspace/api-client-react';
import {
  ChevronDown,
  Download,
  Loader2,
  Play,
  ShieldCheck,
  Square,
} from 'lucide-react';
import { v4 as uuidv4 } from 'uuid';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';
import {
  BENCHMARK_CASES,
  INITIAL_DOCUMENT_HTML,
  type BenchmarkCase,
} from '@/lib/constants';
import {
  type BenchmarkObservation,
  candidateDocumentForResult,
  csvCell,
  downloadText,
  evaluateFormatting,
  getChunkOuterHtml,
  stableDocumentHash,
} from '@/lib/experiment';
import {
  canonicalTelemetryMetadata,
  telemetryMetadataForDocument,
  useLabStore,
} from '@/lib/store';
import {
  applyEditResult,
  DIY_PRICING_VERSION,
  estimateDiyCost,
  estimateRequestContext,
  formatUsd,
  makeRequestFingerprint,
} from '@/lib/telemetry';
import {
  buildEditRequest,
  contextLimitAction,
  createTelemetryDraftForRequest,
} from '@/lib/telemetry-workflows';

function targetForBenchmark(
  documentHtml: string,
  testCase: BenchmarkCase,
): { html: string; text: string } | null {
  if (testCase.scope !== 'selection') return null;
  if (testCase.targetChunkId) {
    const chunk = getChunkOuterHtml(documentHtml, testCase.targetChunkId);
    if (chunk) return chunk;
  }
  const firstBlock = documentHtml.match(
    /<(p|li|blockquote|h[1-6])\b[^>]*>[\s\S]*?<\/\1>/i,
  );
  if (!firstBlock) return null;
  return {
    html: firstBlock[0],
    text: firstBlock[0].replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim(),
  };
}

function errorMessage(error: unknown) {
  if (error && typeof error === 'object' && 'data' in error) {
    const data = (error as { data?: { error?: string } }).data;
    if (data?.error) return data.error;
  }
  return error instanceof Error ? error.message : 'Request failed';
}

function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2;
}

export default function BenchmarkPage() {
  const {
    currentDocumentHtml,
    documentSession,
    benchmarkRuns,
    addBenchmarkRun,
    updateLatestBenchmark,
    logActivity,
    setLatestResults,
    telemetry,
    observabilitySettings,
    recordTelemetry,
    updateTelemetryForRequest,
  } = useLabStore();
  const { data: config } = useGetLabConfig();
  const generateEdit = useGenerateEdit();
  const cancelReview = useCancelReview();
  const stopRef = useRef(false);

  const [declaredBudgetCap, setDeclaredBudgetCap] = useState(25);
  const [runsPerTest, setRunsPerTest] = useState(1);
  const [selectedEngines, setSelectedEngines] = useState<
    Record<EditInputEngine, boolean>
  >({ diy: true, superdocs: true });
  const [acknowledged, setAcknowledged] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [completedRequests, setCompletedRequests] = useState(0);
  const [benchmarkSource, setBenchmarkSource] = useState<'canonical' | 'imported'>(
    'canonical',
  );
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [liveObservations, setLiveObservations] = useState<
    BenchmarkObservation[]
  >([]);

  const engines = (['diy', 'superdocs'] as EditInputEngine[]).filter(
    (engine) => selectedEngines[engine],
  );
  const maximumRequests =
    BENCHMARK_CASES.length * runsPerTest * engines.length;
  const canUseImportedSource = documentSession.sourceType === 'imported';
  const benchmarkDocumentHtml =
    benchmarkSource === 'imported' && canUseImportedSource
      ? currentDocumentHtml
      : INITIAL_DOCUMENT_HTML;
  const configured = useMemo(
    () =>
      new Map(config?.engines.map((engine) => [engine.id, engine]) ?? []),
    [config],
  );
  const unavailableSelected = engines.filter(
    (engine) => !configured.get(engine)?.configured,
  );
  const canRun =
    maximumRequests > 0 &&
    acknowledged &&
    unavailableSelected.length === 0 &&
    declaredBudgetCap >= 0;

  const runBenchmark = async () => {
    if (!canRun) return;
    const contextPlans = BENCHMARK_CASES.flatMap((testCase) => {
      const target = targetForBenchmark(benchmarkDocumentHtml, testCase);
      return engines.map((engine) => ({
        label: `${testCase.label} (${engine})`,
        estimate: estimateRequestContext({
          engine,
          documentHtml: benchmarkDocumentHtml,
          selectionHtml:
            testCase.scope === 'selection' ? target?.html ?? null : null,
          selectionText:
            testCase.scope === 'selection' ? target?.text ?? null : null,
          scope: testCase.scope,
          instruction: testCase.instruction,
          contextBudgetChars: observabilitySettings.contextBudgetChars,
          softContextBudgetChars: observabilitySettings.softContextBudgetChars,
        }),
      }));
    });
    const hardLimitPlan = contextPlans.find(
      (plan) => contextLimitAction(plan.estimate) === 'block',
    );
    if (hardLimitPlan) {
      toast.error(
        `${hardLimitPlan.label} would send ${hardLimitPlan.estimate.contextChars.toLocaleString()} context characters, above the configured application limit.`,
      );
      return;
    }
    const softLimitPlan = contextPlans.find(
      (plan) => contextLimitAction(plan.estimate) === 'confirm',
    );
    if (
      softLimitPlan &&
      !window.confirm(
        `${softLimitPlan.label} will send ${softLimitPlan.estimate.contextChars.toLocaleString()} context characters, above the soft budget. Continue with the benchmark?`,
      )
    ) {
      return;
    }
    setIsRunning(true);
    setCompletedRequests(0);
    setLiveObservations([]);
    stopRef.current = false;
    const observations: BenchmarkObservation[] = [];
    const successfulResults: EditResult[] = [];
    const frozenHtml = benchmarkDocumentHtml;
    const frozenSource =
      benchmarkSource === 'imported' && canUseImportedSource
        ? 'imported'
        : 'canonical';
    const documentMetadata =
      frozenSource === 'imported'
        ? telemetryMetadataForDocument(documentSession, frozenHtml)
        : canonicalTelemetryMetadata(frozenHtml);
    const benchmarkRunId = uuidv4();
    const benchmarkStartedAt = performance.now();
    const startingDocumentHash = stableDocumentHash(frozenHtml);

    outer: for (const testCase of BENCHMARK_CASES) {
      for (let runIndex = 1; runIndex <= runsPerTest; runIndex += 1) {
        for (const engine of engines) {
          if (stopRef.current) break outer;
          const requestId = uuidv4();
          const target = targetForBenchmark(frozenHtml, testCase);
          let result: EditResult | null = null;
          let error: string | null = null;
          if (testCase.scope === 'selection' && !target) {
            error = 'This imported document does not contain a stable text block for the selected-text benchmark case.';
            continue;
          }
          const started = performance.now();
          const modelLabel =
            configured.get(engine)?.modelLabel ?? 'Not configured';
          const requestFingerprint = await makeRequestFingerprint({
            engine,
            documentHtml: frozenHtml,
            selectionHtml: testCase.scope === 'selection' ? target?.html ?? null : null,
            selectionText: testCase.scope === 'selection' ? target?.text ?? null : null,
            scope: testCase.scope,
            instruction: testCase.instruction,
            preset: testCase.label,
          });
          const previous = telemetry.find(
            (record) => record.requestFingerprint === requestFingerprint,
          );
          const request = buildEditRequest({
            engine,
            documentHtml: frozenHtml,
            selectionHtml: testCase.scope === 'selection' ? target?.html ?? null : null,
            selectionText: testCase.scope === 'selection' ? target?.text ?? null : null,
            selectionFrom: null,
            selectionTo: null,
            scope: testCase.scope,
            instruction: testCase.instruction,
            preset: testCase.label,
            requestId,
            currentVersionId: benchmarkRunId,
          });
          const telemetryRecord = recordTelemetry({
            ...(await createTelemetryDraftForRequest({
              request,
              modelLabel,
              link: {
                benchmarkRunId,
                benchmarkCaseId: testCase.id,
              },
              settings: observabilitySettings,
              documentMetadata,
            })),
            duplicateOf: previous?.id ?? null,
            decisionState: 'not_applicable',
          });

          try {
            result = await generateEdit.mutateAsync({ data: request });
            if (result.review) {
              await cancelReview.mutateAsync({
                data: { reviewId: result.review.reviewId },
              });
              error =
                'Hosted review was cancelled after recording its proposal; it was not applied or counted as a completed benchmark result.';
              updateTelemetryForRequest(requestId, engine, {
                ...applyEditResult(telemetryRecord, result),
                outcome: 'cancelled',
                error,
                decisionState: 'stopped',
              });
            } else if (result.success) {
              successfulResults.push(result);
              updateTelemetryForRequest(
                requestId,
                engine,
                applyEditResult(telemetryRecord, result),
              );
            } else {
              updateTelemetryForRequest(
                requestId,
                engine,
                applyEditResult(telemetryRecord, result),
              );
            }
          } catch (caught) {
            error = errorMessage(caught);
            updateTelemetryForRequest(requestId, engine, {
              outcome: 'error',
              error,
              latencyMs: Math.round(performance.now() - started),
              retryCount: null,
            });
          }

          const latencyMs = result?.latencyMs ?? Math.round(performance.now() - started);
          const candidate = result
            ? candidateDocumentForResult(
                frozenHtml,
                testCase,
                result,
              )
            : null;
          const observation: BenchmarkObservation = {
            id: uuidv4(),
            benchmarkRunId,
            testCaseId: testCase.id,
            testLabel: testCase.label,
            runIndex,
            engine,
            startingDocumentHash,
            instruction: testCase.instruction,
            scope: testCase.scope,
            success: Boolean(result?.success && !result?.review && !error),
            latencyMs,
            reviewWaitMs: result?.reviewWaitMs ?? null,
            inputTokens: result?.usage?.inputTokens ?? null,
            outputTokens: result?.usage?.outputTokens ?? null,
            totalTokens: result?.usage?.totalTokens ?? null,
            hostedUsage: result?.usage?.hostedUsage ?? null,
            retryCount: result?.retryCount ?? null,
            formatting: evaluateFormatting(
              frozenHtml,
              candidate,
              testCase.expectedInvariants,
            ),
            error,
            result,
          };
          observations.push(observation);
          setLiveObservations([...observations]);
          setCompletedRequests(observations.length);
          logActivity(
            result?.success && !result?.review && !error
              ? 'Benchmark request completed'
              : 'Benchmark request incomplete',
            `${testCase.label}: ${testCase.instruction}`,
            {
              engine,
              scope: testCase.scope,
              requestId,
              status:
                result?.success && !result?.review && !error
                  ? 'success'
                  : 'error',
              latencyMs,
              retryCount: result?.retryCount ?? null,
              totalTokens: result?.usage?.totalTokens ?? null,
            },
          );
        }
      }
    }

    addBenchmarkRun({
      id: benchmarkRunId,
      config: {
        declaredBudgetCap,
        runsPerTest,
        engines,
        maximumRequests,
        source: frozenSource,
        documentId: documentMetadata.documentId,
      },
      observations,
      actualSpendReported: null,
      totalRuntimeMs: Math.round(performance.now() - benchmarkStartedAt),
      stopped: stopRef.current,
    });
    setLatestResults(successfulResults);
    setIsRunning(false);
    toast[stopRef.current ? 'info' : 'success'](
      stopRef.current
        ? `Benchmark stopped after ${observations.length} requests.`
        : `Benchmark recorded ${observations.length} requests.`,
    );
  };

  const latest = benchmarkRuns[0];
  const displayed = isRunning ? liveObservations : latest?.observations ?? [];
  const successful = displayed.filter((item) => item.success);
  const latencies = successful
    .map((item) => item.latencyMs)
    .filter((value): value is number => value != null);
  const inputTokens = displayed
    .filter((item) => item.engine === 'diy')
    .map((item) => item.inputTokens)
    .filter((value): value is number => value != null);
  const outputTokens = displayed
    .filter((item) => item.engine === 'diy')
    .map((item) => item.outputTokens)
    .filter((value): value is number => value != null);
  const latestTelemetry = latest
    ? telemetry.filter((record) => record.benchmarkRunId === latest.id)
    : [];
  const latestEstimatedCosts = latestTelemetry
    .map(estimateDiyCost)
    .filter(
      (estimate): estimate is { state: 'estimated'; usd: number; label: string } =>
        estimate.state === 'estimated' && estimate.usd != null,
    );
  const latestEstimatedSpend = latestEstimatedCosts.reduce(
    (sum, estimate) => sum + estimate.usd,
    0,
  );
  const latestUnpricedDiy = latestTelemetry.filter(
    (record) =>
      record.engine === 'diy' &&
      estimateDiyCost(record).state === 'not_configured',
  ).length;
  const latestHostedUsageCount = latestTelemetry.filter(
    (record) =>
      record.engine === 'superdocs' && record.usage.hostedUsage != null,
  ).length;
  const latestRetries = latestTelemetry.reduce(
    (sum, record) => sum + (record.retryCount ?? 0),
    0,
  );

  const exportJson = () => {
    if (!latest) return;
    downloadText(
      'benchmark-results.json',
      JSON.stringify(latest, null, 2),
      'application/json',
    );
  };

  const exportCsv = () => {
    if (!latest) return;
    const headers = [
      'test',
      'engine',
      'success',
        'provider_processing_ms',
        'review_wait_ms',
      'input_tokens',
      'output_tokens',
      'retries',
      'hosted_usage',
      'formatting',
        'formatting_detail',
        'tables_before',
        'tables_after',
        'table_preservation',
        'table_structure_before',
        'table_structure_after',
      'error',
      'starting_document_hash',
      'document_source',
      'document_id',
    ];
    const rows = latest.observations.map((item) =>
      [
        item.testLabel,
        item.engine,
        item.success,
        item.latencyMs,
        item.reviewWaitMs ?? 'N/A',
        item.inputTokens ?? 'N/A',
        item.outputTokens ?? 'N/A',
        item.retryCount ?? 'N/A',
        item.hostedUsage ?? 'Not exposed',
        item.formatting.status,
        item.formatting.detail,
        item.formatting.before.tables,
        item.formatting.after.tables,
        item.formatting.before.tables === item.formatting.after.tables
          ? item.formatting.tablePreservation.preserved
            ? 'preserved'
            : 'structure_changed'
          : 'changed',
        item.formatting.tablePreservation.before
          .map((table) => table.id)
          .join('; ') || 'none',
        item.formatting.tablePreservation.after
          .map((table) => table.id)
          .join('; ') || 'none',
        item.error ?? '',
        item.startingDocumentHash,
        latest.config.source ?? 'canonical',
        latest.config.documentId ?? 'canonical-demo',
      ]
        .map(csvCell)
        .join(','),
    );
    downloadText(
      'benchmark-results.csv',
      [headers.join(','), ...rows].join('\n'),
      'text/csv',
    );
  };

  const exportMarkdown = () => {
    if (!latest) return;
    const rows = latest.observations
      .map(
        (item) =>
          `| ${item.testLabel} | ${item.engine} | ${item.success ? 'Yes' : 'No'} | ${item.latencyMs ?? 'N/A'} | ${item.reviewWaitMs ?? 'N/A'} | ${item.inputTokens ?? 'Not exposed'} | ${item.outputTokens ?? 'Not exposed'} | ${item.hostedUsage ?? 'Not exposed'} | ${item.formatting.status} | ${item.formatting.before.tables}→${item.formatting.after.tables} (${item.formatting.tablePreservation.preserved ? 'structure preserved' : 'structure changed'}) | ${item.error ?? ''} |`,
      )
      .join('\n');
    const markdown = `# AI Editing Lab Comparison

## Experiment Configuration

- Date: ${latest.timestamp}
- Declared budget cap: ${latest.config.declaredBudgetCap}
- Document source: ${latest.config.source ?? 'canonical'}
- Document identity: ${latest.config.documentId ?? 'canonical-demo'}
- Runs per test: ${latest.config.runsPerTest}
- Engines: ${latest.config.engines.join(', ')}
- Maximum requests: ${latest.config.maximumRequests}
- Total runtime: ${latest.totalRuntimeMs?.toLocaleString() ?? 'Not recorded'} ms
- Actual spend reported: ${latest.actualSpendReported ?? 'Not entered'}
- DIY estimated spend (${DIY_PRICING_VERSION}): ${latestEstimatedCosts.length ? formatUsd(latestEstimatedSpend) : latestUnpricedDiy ? 'Pricing not configured for one or more DIY requests' : 'Not measured'}
- Hosted usage exposed on ${latestHostedUsageCount} request(s); raw model tokens, direct model cost, and TTFT are not exposed by SuperDocs.

## Results

| Test | Engine | Success | Provider processing (ms) | Reviewer wait (ms) | Input tokens | Output tokens | Hosted response data | Formatting | Tables before→after | Error |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
${rows}

## Aggregate Metrics

- Successful requests: ${latest.observations.filter((item) => item.success).length}
- Failed requests: ${latest.observations.filter((item) => !item.success).length}
- Median provider processing time: ${median(latest.observations.map((item) => item.latencyMs).filter((value): value is number => value != null)) ?? 'N/A'} ms
- DIY input tokens: ${inputTokens.length ? inputTokens.reduce((sum, value) => sum + value, 0) : 'Not exposed'}
- DIY output tokens: ${outputTokens.length ? outputTokens.reduce((sum, value) => sum + value, 0) : 'Not exposed'}
- Retries: ${latestRetries}

## Reviewer Scores

Manual scores are recorded in the Compare view.

## Observed Failures

${latest.observations.filter((item) => item.error).map((item) => `- ${item.testLabel} / ${item.engine}: ${item.error}`).join('\n') || 'None recorded.'}

## Data Availability

SuperDocs may return account-level usage metadata but does not expose per-request model token counts. Missing data is not treated as zero.

## Notes

No automatic conclusion is generated. Add qualitative observations here.
`;
    downloadText('comparison-report.md', markdown, 'text/markdown');
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 md:p-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Benchmark</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          A repeatable test run for measuring how the editing engines handle the
          same five tasks. It is separate from Compare: Benchmark runs
          predefined tests and records measurements; Compare lets you give both
          engines one instruction and manually judge the outputs.
        </p>
      </header>

      <Card>
        <CardContent className="space-y-4 p-4 md:p-6">
          <div className="space-y-4 rounded-md border bg-muted/10 p-4">
            <div>
              <h2 className="text-sm font-semibold">How this benchmark works</h2>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                A benchmark run is a controlled measurement, not an automatic
                quality verdict. It sends the same input to the selected engine
                or engines and keeps every request in one exportable report.
              </p>
            </div>
            <ol className="grid gap-3 text-xs md:grid-cols-4">
              <li className="rounded border bg-background p-3">
                <strong className="block text-sm">1. Choose the source</strong>
                <span className="mt-1 block leading-relaxed text-muted-foreground">
                  Use the standard test document, or choose the current imported
                  document after uploading one in Editor or Compare.
                </span>
              </li>
              <li className="rounded border bg-background p-3">
                <strong className="block text-sm">2. Run five tasks</strong>
                <span className="mt-1 block leading-relaxed text-muted-foreground">
                  Each task tests a different editing behavior, from grammar
                  correction to a document-level insertion.
                </span>
              </li>
              <li className="rounded border bg-background p-3">
                <strong className="block text-sm">3. Record evidence</strong>
                <span className="mt-1 block leading-relaxed text-muted-foreground">
                  The report records success, response time, retries, available
                  token or usage data, and formatting checks.
                </span>
              </li>
              <li className="rounded border bg-background p-3">
                <strong className="block text-sm">4. Review limits</strong>
                <span className="mt-1 block leading-relaxed text-muted-foreground">
                  Formatting checks are automated; meaning, tone, and usefulness
                  still need human review. No winner is declared automatically.
                </span>
              </li>
            </ol>
            <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
              <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
              Fairness guarantee: every request starts from the same frozen
              document. SuperDocs hosted review jobs are recorded and then
              cancelled, so no benchmark result changes a document.
            </p>
          </div>

          <Collapsible open={settingsOpen} onOpenChange={setSettingsOpen}>
            <CollapsibleTrigger asChild>
              <button
                type="button"
                className="flex w-full items-center justify-between rounded-md border bg-muted/20 px-3 py-2 text-sm"
                data-testid="button-benchmark-settings"
              >
                <span>
                  Benchmark settings
                  <span className="ml-2 text-xs text-muted-foreground">
                    {runsPerTest} run{runsPerTest > 1 ? 's' : ''} per test ·{' '}
                    {engines.length} engine{engines.length === 1 ? '' : 's'} ·{' '}
                    {benchmarkSource === 'imported' && canUseImportedSource
                      ? 'your uploaded document'
                      : 'standard document'}
                  </span>
                </span>
                <ChevronDown
                  className={`h-4 w-4 transition-transform ${settingsOpen ? 'rotate-180' : ''}`}
                />
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="mt-3 space-y-4 rounded-md border p-4">
                <div className="grid gap-4 md:grid-cols-4">
                  <div className="space-y-2">
                    <Label htmlFor="budget">Declared budget cap</Label>
                    <Input
                      id="budget"
                      type="number"
                      min={0}
                      step={1}
                      value={declaredBudgetCap}
                      onChange={(event) =>
                        setDeclaredBudgetCap(Number(event.target.value))
                      }
                      disabled={isRunning}
                      data-testid="input-budget-cap"
                    />
                    <p className="text-[10px] text-muted-foreground">
                      Guard only; not an API cost estimate.
                    </p>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="runs-per-test">Runs per test</Label>
                    <Input
                      id="runs-per-test"
                      type="number"
                      min={1}
                      max={3}
                      value={runsPerTest}
                      onChange={(event) => {
                        setRunsPerTest(
                          Math.min(3, Math.max(1, Number(event.target.value))),
                        );
                        setAcknowledged(false);
                      }}
                      disabled={isRunning}
                      data-testid="input-runs-per-test"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Engines</Label>
                    {(['diy', 'superdocs'] as EditInputEngine[]).map(
                      (engine) => (
                        <label
                          key={engine}
                          className="flex items-center gap-2 text-sm"
                        >
                          <Checkbox
                            checked={selectedEngines[engine]}
                            onCheckedChange={(checked) => {
                              setSelectedEngines((current) => ({
                                ...current,
                                [engine]: checked === true,
                              }));
                              setAcknowledged(false);
                            }}
                            disabled={isRunning}
                            data-testid={`checkbox-engine-${engine}`}
                          />
                          {configured.get(engine)?.label ??
                            (engine === 'diy' ? 'DIY Toolkit' : 'SuperDocs')}
                          {!configured.get(engine)?.configured && (
                            <span className="text-[10px] text-amber-600">
                              unavailable
                            </span>
                          )}
                        </label>
                      ),
                    )}
                  </div>
                  <div className="space-y-2">
                    <Label>Benchmark source</Label>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="radio"
                        name="benchmark-source"
                        checked={benchmarkSource === 'canonical'}
                        onChange={() => {
                          setBenchmarkSource('canonical');
                          setAcknowledged(false);
                        }}
                        disabled={isRunning}
                        data-testid="radio-source-canonical"
                      />
                      Standard benchmark document
                    </label>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="radio"
                        name="benchmark-source"
                        checked={benchmarkSource === 'imported'}
                        onChange={() => {
                          setBenchmarkSource('imported');
                          setAcknowledged(false);
                        }}
                        disabled={isRunning || !canUseImportedSource}
                        data-testid="radio-source-imported"
                      />
                      Current imported document
                    </label>
                    {!canUseImportedSource && (
                      <p className="text-[10px] text-muted-foreground">
                        Upload a document in the Editor to enable this source.
                      </p>
                    )}
                  </div>
                </div>

                {unavailableSelected.length > 0 && (
                  <p className="rounded-md border border-amber-500/30 bg-amber-500/5 p-2.5 text-xs text-muted-foreground">
                    Uncheck unavailable engines or configure them before running.
                    Configure each selected engine before running. SuperDocs requires
                    a server-side SUPERDOCS_API_KEY.
                  </p>
                )}
                {benchmarkSource === 'imported' && canUseImportedSource && (
                  <p className="rounded-md border border-amber-500/30 bg-amber-500/5 p-2.5 text-xs text-amber-800 dark:text-amber-200">
                    Custom-document benchmark results may not be directly comparable with previous benchmark runs.
                  </p>
                )}
              </div>
            </CollapsibleContent>
          </Collapsible>

          <label className="flex items-start gap-2 rounded-md border p-3 text-sm">
            <Checkbox
              checked={acknowledged}
              onCheckedChange={(checked) =>
                setAcknowledged(checked === true)
              }
              disabled={isRunning}
              data-testid="checkbox-acknowledge"
            />
            <span>
              I understand this will make up to{' '}
              <strong>{maximumRequests} API requests</strong>.
            </span>
          </label>

          <div className="flex items-center justify-between gap-4">
            <div className="min-w-0 flex-1">
              {isRunning && (
                <>
                  <div className="mb-1 flex justify-between text-xs text-muted-foreground">
                    <span>
                      Working through the tests — request{' '}
                      {Math.min(completedRequests + 1, maximumRequests)} of{' '}
                      {maximumRequests}
                    </span>
                    <span>
                      {completedRequests}/{maximumRequests} done
                    </span>
                  </div>
                  <Progress
                    value={
                      maximumRequests
                        ? (completedRequests / maximumRequests) * 100
                        : 0
                    }
                    className="h-2"
                  />
                </>
              )}
            </div>
            {isRunning ? (
              <Button
                variant="destructive"
                onClick={() => {
                  stopRef.current = true;
                }}
                data-testid="button-stop-benchmark"
              >
                <Square className="mr-2 h-4 w-4" />
                Stop benchmark
              </Button>
            ) : (
              <Button onClick={runBenchmark} disabled={!canRun} data-testid="button-start-benchmark">
                {generateEdit.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Play className="mr-2 h-4 w-4" />
                )}
                Start benchmark
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      <section>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          What the five tests measure
        </p>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          {BENCHMARK_CASES.map((testCase, index) => (
            <Card key={testCase.id}>
              <CardContent className="p-3">
                <p className="font-mono text-[10px] text-primary">
                  TEST {String(index + 1).padStart(2, '0')}
                </p>
                <h2 className="mt-1 text-sm font-semibold">
                  {testCase.label}
                </h2>
                <p className="mt-2 text-[10px] font-semibold uppercase tracking-wide text-primary">
                  What it checks
                </p>
                <p className="mt-1 line-clamp-4 text-[11px] leading-relaxed text-muted-foreground">
                  {testCase.purpose}
                </p>
                <p className="mt-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Instruction sent
                </p>
                <p className="mt-1 line-clamp-3 text-[11px] leading-relaxed text-muted-foreground">
                  {testCase.instruction}
                </p>
                <Badge variant="outline" className="mt-3 text-[9px]">
                  {testCase.scope === 'selection'
                    ? 'selected paragraph'
                    : 'whole document'}
                </Badge>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {(displayed.length > 0 || latest) && (
        <Card data-testid="section-benchmark-results">
          <CardHeader className="flex-row items-start justify-between gap-4">
            <div>
              <CardTitle className="text-base">Results</CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">
                {successful.length} of {displayed.length} requests completed
                successfully
                {median(latencies) != null
                  ? ` · typical response ${((median(latencies) as number) / 1000).toFixed(1)}s`
                  : ''}{' '}
                · small sample — indicative, not statistically significant
              </p>
            </div>
            {!isRunning && latest && (
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" size="sm" onClick={exportJson} data-testid="button-export-benchmark-json">
                  <Download className="mr-1.5 h-3.5 w-3.5" />
                  JSON
                </Button>
                <Button variant="outline" size="sm" onClick={exportCsv} data-testid="button-export-benchmark-csv">
                  CSV
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={exportMarkdown}
                  data-testid="button-export-benchmark-md"
                >
                  Markdown report
                </Button>
              </div>
            )}
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 md:grid-cols-5">
              <div className="rounded border p-3">
                <p className="text-[10px] uppercase text-muted-foreground">
                  Mean latency
                </p>
                <p className="font-mono text-xl font-semibold">
                  {latencies.length
                    ? Math.round(
                        latencies.reduce((sum, value) => sum + value, 0) /
                          latencies.length,
                      )
                    : 'N/A'}{' '}
                  <span className="text-xs font-normal">ms</span>
                </p>
              </div>
              <div className="rounded border p-3">
                <p className="text-[10px] uppercase text-muted-foreground">
                  DIY input tokens
                </p>
                <p className="font-mono text-xl font-semibold">
                  {inputTokens.length
                    ? inputTokens.reduce((sum, value) => sum + value, 0)
                    : 'Not exposed'}
                </p>
              </div>
              <div className="rounded border p-3">
                <p className="text-[10px] uppercase text-muted-foreground">
                  DIY output tokens
                </p>
                <p className="font-mono text-xl font-semibold">
                  {outputTokens.length
                    ? outputTokens.reduce((sum, value) => sum + value, 0)
                    : 'Not exposed'}
                </p>
              </div>
              <div className="rounded border p-3">
                <p className="text-[10px] uppercase text-muted-foreground">
                  Formatting checks
                </p>
                <p className="font-mono text-sm font-semibold">
                  {['PASS', 'PARTIAL', 'FAIL', 'N/A']
                    .map(
                      (status) =>
                        `${status} ${
                          displayed.filter(
                            (item) => item.formatting.status === status,
                          ).length
                        }`,
                    )
                    .join(' · ')}
                </p>
              </div>
              <div className="rounded border border-primary/20 bg-primary/5 p-3">
                <p className="text-[10px] uppercase text-muted-foreground">
                  DIY estimated spend
                </p>
                <p className="font-mono text-xl font-semibold">
                  {latestEstimatedCosts.length
                    ? formatUsd(latestEstimatedSpend)
                    : latestUnpricedDiy
                      ? 'Not configured'
                      : 'Not measured'}
                </p>
                <p className="mt-1 text-[10px] text-muted-foreground">
                  {latest ? `Pricing ${DIY_PRICING_VERSION}` : 'Current run updates after completion'}
                </p>
              </div>
            </div>

            {!isRunning && latest && (
              <div className="grid gap-3 rounded-md border bg-muted/20 p-3 text-xs md:grid-cols-4">
                <div>
                  <p className="text-muted-foreground">Total runtime</p>
                  <p className="mt-1 font-mono font-semibold">
                    {latest.totalRuntimeMs?.toLocaleString() ?? 'Not recorded'} ms
                  </p>
                </div>
                <div>
                  <p className="text-muted-foreground">Retries</p>
                  <p className="mt-1 font-mono font-semibold">{latestRetries}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Hosted usage</p>
                  <p className="mt-1 font-mono font-semibold">
                    {latestHostedUsageCount
                      ? `${latestHostedUsageCount} exposed`
                      : 'Not exposed'}
                  </p>
                </div>
                <div>
                  <p className="text-muted-foreground">Declared limits</p>
                  <p className="mt-1 font-mono font-semibold">
                    {latest.config.maximumRequests} requests · {latest.config.declaredBudgetCap} budget cap
                  </p>
                </div>
              </div>
            )}

            <div className="overflow-x-auto rounded-md border">
              <table className="w-full min-w-[900px] text-left text-xs">
                <thead className="border-b bg-muted/50 text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 font-medium">Test</th>
                    <th className="px-3 py-2 font-medium">Engine</th>
                    <th className="px-3 py-2 font-medium">Success</th>
                    <th className="px-3 py-2 font-medium">Latency</th>
                    <th className="px-3 py-2 font-medium">Tokens</th>
                    <th className="px-3 py-2 font-medium">Retries</th>
                    <th className="px-3 py-2 font-medium">Formatting</th>
                    <th className="px-3 py-2 font-medium">Error</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {displayed.map((item) => (
                    <tr key={item.id}>
                      <td className="px-3 py-2 font-medium">
                        {item.testLabel}
                      </td>
                      <td className="px-3 py-2">{item.engine}</td>
                      <td className="px-3 py-2">
                        {item.success ? 'Yes' : 'No'}
                      </td>
                      <td className="px-3 py-2 font-mono">
                        {item.latencyMs ?? 'N/A'} ms
                      </td>
                      <td className="px-3 py-2 font-mono">
                        {item.totalTokens ?? 'Not exposed'}
                      </td>
                      <td className="px-3 py-2 font-mono">
                        {item.retryCount ?? 'N/A'}
                      </td>
                      <td className="px-3 py-2">
                        <Badge variant="outline">
                          {item.formatting.status}
                          <span className="ml-1 font-mono text-muted-foreground">
                            {item.formatting.before.tables}→{item.formatting.after.tables}
                            {item.formatting.tablePreservation.preserved
                              ? ' structure intact'
                              : ' structure changed'}
                          </span>
                        </Badge>
                      </td>
                      <td className="max-w-56 truncate px-3 py-2 text-muted-foreground">
                        {item.error ?? '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {!isRunning && latest && (
              <div className="flex items-end gap-3 border-t pt-4">
                <div className="space-y-2">
                  <Label htmlFor="actual-spend">
                    Actual spend reported
                  </Label>
                  <Input
                    id="actual-spend"
                    type="number"
                    min={0}
                    step="0.01"
                    className="w-44"
                    value={latest.actualSpendReported ?? ''}
                    onChange={(event) =>
                      updateLatestBenchmark({
                        actualSpendReported:
                          event.target.value === ''
                            ? null
                            : Number(event.target.value),
                      })
                    }
                    placeholder="From dashboards"
                    data-testid="input-actual-spend"
                  />
                </div>
                <p className="pb-2 text-[10px] text-muted-foreground">
                  Manual evidence only. No stale pricing is hardcoded.
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
