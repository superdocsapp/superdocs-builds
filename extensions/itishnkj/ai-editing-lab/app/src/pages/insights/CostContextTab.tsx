import { useMemo, useState, type ComponentType, type ReactNode } from 'react';
import { format } from 'date-fns';
import { useLabStore } from '@/lib/store';
import { usePreferences } from '@/lib/preferences';
import {
  DIY_PRICING_VERSION,
  estimateDiyCost,
  formatMetric,
  formatUsd,
} from '@/lib/telemetry';
import type { TelemetryRecord } from '@/lib/telemetry';
import { downloadText } from '@/lib/experiment';
import {
  shouldClearTelemetry,
  telemetryCsv,
  telemetryJson,
  telemetryMarkdown,
} from '@/lib/telemetry-exports';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

import {
  Activity,
  AlertCircle,
  BarChart3,
  CheckCircle2,
  Clock,
  Coins,
  Database,
  Download,
  FileJson,
  FileText,
  Settings2,
  Trash2,
} from 'lucide-react';

const SESSION_STARTED_AT = new Date().toISOString();

type Metrics = {
  requests: number;
  diyRequests: number;
  hostedRequests: number;
  successes: number;
  retries: number;
  accepted: number;
  rejected: number;
  diyInputTokens: number;
  diyOutputTokens: number;
  contextChars: number;
  averageLatency: number | null;
  estimatedSpend: number;
  estimatedSpendCount: number;
  unpricedDiyCount: number;
  hostedUsageCount: number;
};

function summarize(records: TelemetryRecord[]): Metrics {
  const latency = records
    .map((record) => record.latencyMs)
    .filter((value): value is number => value != null);
  return records.reduce<Metrics>(
    (summary, record) => {
      const estimate = estimateDiyCost(record);
      summary.requests += 1;
      summary.successes += record.outcome === 'success' ? 1 : 0;
      summary.retries += record.retryCount ?? 0;
      summary.accepted += record.decisionState === 'accepted' ? 1 : 0;
      summary.rejected += record.decisionState === 'rejected' ? 1 : 0;
      summary.contextChars += record.contextChars;
      if (record.engine === 'diy') {
        summary.diyRequests += 1;
        summary.diyInputTokens += record.usage.inputTokens ?? 0;
        summary.diyOutputTokens += record.usage.outputTokens ?? 0;
        if (estimate.usd != null) {
          summary.estimatedSpend += estimate.usd;
          summary.estimatedSpendCount += 1;
        }
        if (estimate.state === 'not_configured') summary.unpricedDiyCount += 1;
      } else {
        summary.hostedRequests += 1;
        if (record.usage.hostedUsage) summary.hostedUsageCount += 1;
      }
      return summary;
    },
    {
      requests: 0,
      diyRequests: 0,
      hostedRequests: 0,
      successes: 0,
      retries: 0,
      accepted: 0,
      rejected: 0,
      diyInputTokens: 0,
      diyOutputTokens: 0,
      contextChars: 0,
      averageLatency: latency.length
        ? latency.reduce((sum, value) => sum + value, 0) / latency.length
        : null,
      estimatedSpend: 0,
      estimatedSpendCount: 0,
      unpricedDiyCount: 0,
      hostedUsageCount: 0,
    },
  );
}

function spendLabel(metrics: Metrics): string {
  if (metrics.estimatedSpendCount) return formatUsd(metrics.estimatedSpend);
  if (metrics.unpricedDiyCount) return 'Pricing not configured';
  return 'Not measured';
}

const StatCard = ({ title, value, subValue, icon: Icon }: { title: string; value: string | number; subValue: string; icon: ComponentType<{ className?: string }> }) => (
  <Card className="shadow-sm overflow-hidden relative border-l-4 border-l-primary/60 hover:border-l-primary transition-colors bg-card">
    <div className="absolute -top-4 -right-4 p-4 opacity-[0.03] pointer-events-none text-primary">
      <Icon className="w-24 h-24" />
    </div>
    <CardHeader className="pb-2">
      <CardTitle className="text-xs font-semibold text-muted-foreground tracking-wider uppercase">{title}</CardTitle>
    </CardHeader>
    <CardContent>
      <div className="text-3xl font-bold text-foreground font-sans tracking-tight">{value}</div>
      {subValue && <p className="text-xs text-muted-foreground mt-1 font-mono">{subValue}</p>}
    </CardContent>
  </Card>
);

const CorrelationCard = ({ telemetry }: { telemetry: TelemetryRecord[] }) => {
  const superDocsReqs = telemetry.filter(t => t.engine === 'superdocs' && t.outcome === 'success').length;
  const diyReqs = telemetry.filter(t => t.engine === 'diy' && t.outcome === 'success').length;

  const sufficient = superDocsReqs >= 5 && diyReqs >= 5;

  return (
    <Card className="shadow-sm border-primary/20 bg-primary/[0.02] h-full flex flex-col">
      <CardHeader className="pb-2 border-b border-primary/10">
        <CardTitle className="text-sm font-semibold flex items-center gap-2 text-primary uppercase tracking-wider">
          <BarChart3 className="w-4 h-4" />
          Economics Correlation
        </CardTitle>
        <CardDescription className="text-xs">
          DIY Cost vs Hosted Efficiency
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-5 flex-1 flex flex-col justify-center">
        {sufficient ? (
           <div className="space-y-3">
             <div className="text-base font-bold text-foreground">Uncorrelated</div>
             <p className="text-xs text-muted-foreground leading-relaxed">
               SuperDocs obscures exact tokens and Time-To-First-Token (TTFT). Direct mapping to DIY economics remains statistically invalid despite adequate sample size ({superDocsReqs} Hosted, {diyReqs} DIY).
             </p>
           </div>
        ) : (
          <div className="space-y-3">
             <div className="text-base font-bold text-muted-foreground">Insufficient Sample</div>
             <p className="text-xs text-muted-foreground leading-relaxed">
               Correlation requires at least 5 successful requests per engine to establish statistical baselines.
             </p>
             <div className="flex gap-4 mt-2 text-xs font-mono">
               <div className="flex items-center gap-1">
                 <span className={superDocsReqs >= 5 ? "text-primary font-bold" : "text-muted-foreground"}>{superDocsReqs}/5</span> SD
               </div>
               <div className="flex items-center gap-1">
                 <span className={diyReqs >= 5 ? "text-primary font-bold" : "text-muted-foreground"}>{diyReqs}/5</span> DIY
               </div>
             </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
};

const BudgetControls = () => {
  const { observabilitySettings, setObservabilitySettings } = useLabStore();
  const [localSettings, setLocalSettings] = useState(observabilitySettings);

  const handleSave = () => {
    setObservabilitySettings(localSettings);
  };

  const isDirty =
    localSettings.sessionBudgetUsd !== observabilitySettings.sessionBudgetUsd ||
    localSettings.contextBudgetChars !== observabilitySettings.contextBudgetChars ||
    localSettings.softContextBudgetChars !== observabilitySettings.softContextBudgetChars;

  return (
    <Card className="shadow-sm border-primary/20 bg-primary/[0.02]">
      <CardHeader className="pb-4 border-b border-primary/10">
        <CardTitle className="text-sm font-semibold flex items-center gap-2 text-primary uppercase tracking-wider">
          <Settings2 className="w-4 h-4" />
          Budget & Context Limits
        </CardTitle>
        <CardDescription className="text-xs">
          Alert thresholds and hard limits for request telemetry. Adjustments apply to future requests.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid grid-cols-1 md:grid-cols-3 gap-6 pt-5">
        <div className="space-y-2">
          <Label className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Session Budget (USD)</Label>
          <div className="relative">
            <span className="absolute left-3 top-2 text-muted-foreground text-sm">$</span>
            <Input
              type="number"
              className="pl-7 font-mono text-sm h-9"
              step="0.01"
              value={localSettings.sessionBudgetUsd ?? ''}
              onChange={(e) => setLocalSettings(s => ({ ...s, sessionBudgetUsd: e.target.value ? Number(e.target.value) : null }))}
              placeholder="e.g. 5.00"
              data-testid="input-session-budget"
            />
          </div>
        </div>
        <div className="space-y-2">
          <Label className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Context Hard Limit (Chars)</Label>
          <Input
            type="number"
            className="font-mono text-sm h-9"
            value={localSettings.contextBudgetChars}
            onChange={(e) => setLocalSettings(s => ({ ...s, contextBudgetChars: Number(e.target.value) }))}
            data-testid="input-context-hard-limit"
          />
        </div>
        <div className="space-y-2">
          <Label className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Context Soft Limit (Chars)</Label>
          <Input
            type="number"
            className="font-mono text-sm h-9"
            value={localSettings.softContextBudgetChars}
            onChange={(e) => setLocalSettings(s => ({ ...s, softContextBudgetChars: Number(e.target.value) }))}
            data-testid="input-context-soft-limit"
          />
        </div>
      </CardContent>
      <CardFooter className="bg-primary/5 py-3 border-t border-primary/10 flex justify-end">
        <Button
          onClick={handleSave}
          disabled={!isDirty}
          size="sm"
          className="w-full md:w-auto font-medium text-xs h-8"
          data-testid="button-save-thresholds"
        >
          {isDirty ? 'Save Thresholds' : 'Thresholds Saved'}
        </Button>
      </CardFooter>
    </Card>
  );
};

const RowDetailsDialog = ({ record, developerMode, children }: { record: TelemetryRecord; developerMode: boolean; children: ReactNode }) => {
  const est = estimateDiyCost(record);

  return (
    <Dialog>
      <DialogTrigger asChild>
        {children}
      </DialogTrigger>
      <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto border-primary/20">
        <DialogHeader className="border-b pb-4 mb-4">
          <DialogTitle className="flex items-center gap-3 text-lg">
            Request {developerMode && <span className="font-mono text-muted-foreground text-sm">{record.id}</span>}
            <Badge variant={record.outcome === 'success' ? 'default' : record.outcome === 'error' ? 'destructive' : 'secondary'} className="uppercase tracking-wider text-[10px]">
              {record.outcome}
            </Badge>
          </DialogTitle>
        </DialogHeader>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          <div className="space-y-6">
            <section>
              <h4 className="font-semibold text-xs text-primary uppercase tracking-wider mb-3">Configuration</h4>
              <div className="grid grid-cols-2 gap-y-3 gap-x-4 text-sm bg-muted/30 p-3 rounded-md border">
                <span className="text-muted-foreground">Engine</span>
                <span className="font-mono font-medium">{record.engine}</span>
                <span className="text-muted-foreground">Model</span>
                <span className="font-mono font-medium">{record.modelLabel}</span>
                <span className="text-muted-foreground">Scope</span>
                <span className="font-mono font-medium">{record.scope}</span>
                 <span className="text-muted-foreground">Prompt version</span>
                 <span className="font-mono font-medium">{record.promptVersion}</span>
                 <span className="text-muted-foreground">Document source</span>
                 <span className="font-mono font-medium">
                   {record.documentSource ?? 'canonical'}
                   {record.fileType ? ` · ${record.fileType.toUpperCase()}` : ''}
                 </span>
                 {developerMode && (
                   <>
                     <span className="text-muted-foreground">Document identity</span>
                     <span className="font-mono font-medium truncate" title={record.documentId}>
                       {record.documentId ?? 'canonical-demo'}
                     </span>
                   </>
                 )}
                 <span className="text-muted-foreground">Decision</span>
                 <span className="font-mono font-medium">{record.decisionState}</span>
                <span className="text-muted-foreground">Timestamp</span>
                <span className="font-mono font-medium">{format(new Date(record.createdAt), 'yyyy-MM-dd HH:mm:ss')}</span>
              </div>
            </section>

            <section>
              <h4 className="font-semibold text-xs text-primary uppercase tracking-wider mb-3">Performance & Cost</h4>
              <div className="grid grid-cols-2 gap-y-3 gap-x-4 text-sm bg-muted/30 p-3 rounded-md border">
                <span className="text-muted-foreground">Latency</span>
                 <span className="font-mono font-medium">{record.latencyMs != null ? `${record.latencyMs}ms` : 'Not measured'}</span>
                <span className="text-muted-foreground">Retry Count</span>
                <span className="font-mono font-medium">{record.retryCount ?? 0}</span>

                {record.engine === 'diy' ? (
                  <>
                    <span className="text-muted-foreground">Est. Cost</span>
                    <span className="font-mono font-medium">{formatUsd(est.usd)}</span>
                    <span className="text-muted-foreground">Input Tokens</span>
                    <span className="font-mono font-medium">{formatMetric(record.usage.inputTokens)}</span>
                    <span className="text-muted-foreground">Output Tokens</span>
                    <span className="font-mono font-medium">{formatMetric(record.usage.outputTokens)}</span>
                  </>
                ) : (
                  <>
                    <span className="text-muted-foreground">Hosted Usage</span>
                    <span className="font-mono font-medium">{record.usage.hostedUsage || 'Not exposed'}</span>
                    <span className="text-muted-foreground">Raw Tokens</span>
                     <span className="font-mono text-muted-foreground italic">Not exposed</span>
                     <span className="text-muted-foreground">Direct model cost</span>
                     <span className="font-mono text-muted-foreground italic">Not exposed</span>
                     <span className="text-muted-foreground">TTFT</span>
                     <span className="font-mono text-muted-foreground italic">Not measured</span>
                  </>
                )}
              </div>
            </section>
          </div>

          <div className="space-y-6">
            <section>
              <h4 className="font-semibold text-xs text-primary uppercase tracking-wider mb-3">Context Efficiency</h4>
              <div className="grid grid-cols-2 gap-y-3 gap-x-4 text-sm bg-muted/30 p-3 rounded-md border">
                <span className="text-muted-foreground">Strategy</span>
                <span className="font-mono font-medium truncate" title={record.contextStrategy}>{record.contextStrategy}</span>
                <span className="text-muted-foreground">Document Size</span>
                <span className="font-mono font-medium">{record.documentChars.toLocaleString()} chars</span>
                <span className="text-muted-foreground">Imported text</span>
                <span className="font-mono font-medium">
                  {(record.documentWordCount ?? 0).toLocaleString()} words · {(record.documentCharacterCount ?? record.documentChars).toLocaleString()} chars
                </span>
                <span className="text-muted-foreground">Selection Size</span>
                <span className="font-mono font-medium">{record.selectionChars.toLocaleString()} chars</span>
                <span className="text-muted-foreground border-t pt-2 mt-1">Context Sent</span>
                <span className="font-mono font-medium border-t pt-2 mt-1">{record.contextChars.toLocaleString()} chars</span>
                <span className="text-muted-foreground">Prompt Total</span>
                <span className="font-mono font-medium">{record.promptChars.toLocaleString()} chars</span>
              </div>
            </section>

            {developerMode ? (
              <section>
                <h4 className="font-semibold text-xs text-primary uppercase tracking-wider mb-3">Traceability</h4>
                <div className="flex flex-col gap-3 text-xs bg-muted/30 p-3 rounded-md border">
                  <div className="flex flex-col gap-1">
                     <span className="text-muted-foreground font-semibold uppercase">Opaque request fingerprint</span>
                     <span className="font-mono bg-background p-1.5 rounded border break-all text-primary">{record.requestFingerprint}</span>
                  </div>
                  <div className="flex flex-col gap-1">
                     <span className="text-muted-foreground font-semibold uppercase">Opaque instruction fingerprint</span>
                     <span className="font-mono bg-background p-1.5 rounded border break-all">{record.instructionFingerprint}</span>
                  </div>
                   <div className="flex flex-col gap-1">
                     <span className="text-muted-foreground font-semibold uppercase">Experiment link</span>
                     <span className="font-mono bg-background p-1.5 rounded border">
                       {record.benchmarkRunId
                         ? `Benchmark ${record.benchmarkRunId}`
                         : record.compareRunId
                           ? `Comparison ${record.compareRunId}`
                           : 'Standalone editor request'}
                     </span>
                   </div>
                </div>
              </section>
            ) : (
              <p className="rounded-md border bg-muted/20 p-3 text-xs text-muted-foreground">
                Request fingerprints and trace links are hidden. Turn on
                Developer Mode in Settings to see them — the data is always
                recorded either way.
              </p>
            )}
          </div>

          {record.error && (
            <div className="col-span-1 md:col-span-2 mt-2">
              <h4 className="font-semibold text-xs text-destructive uppercase tracking-wider mb-3">Error Details</h4>
              <div className="bg-destructive/10 text-destructive p-4 rounded-md border border-destructive/20 text-sm font-mono whitespace-pre-wrap break-all">
                {record.error}
              </div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};

export function CostContextTab() {
  const { telemetry, clearTelemetry, observabilitySettings } = useLabStore();
  const { preferences } = usePreferences();
  const developerMode = preferences.developerMode;

  const [engineFilter, setEngineFilter] = useState<'all' | 'diy' | 'superdocs'>('all');
  const [outcomeFilter, setOutcomeFilter] = useState<
    'all' | TelemetryRecord['outcome']
  >('all');

  const filteredTelemetry = useMemo(() => {
    return telemetry.filter(t => {
      if (engineFilter !== 'all' && t.engine !== engineFilter) return false;
      if (outcomeFilter !== 'all' && t.outcome !== outcomeFilter) return false;
      return true;
    });
  }, [telemetry, engineFilter, outcomeFilter]);

  const allTime = useMemo(() => summarize(telemetry), [telemetry]);
  const today = useMemo(() => {
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    return summarize(
      telemetry.filter(
        (record) => new Date(record.createdAt).getTime() >= start.getTime(),
      ),
    );
  }, [telemetry]);
  const session = useMemo(
    () =>
      summarize(
        telemetry.filter(
          (record) => record.createdAt >= SESSION_STARTED_AT,
        ),
      ),
    [telemetry],
  );
  const benchmark = useMemo(
    () => summarize(telemetry.filter((record) => record.benchmarkRunId != null)),
    [telemetry],
  );
  const mostExpensive = useMemo(
    () =>
      telemetry
        .filter((record) => estimateDiyCost(record).usd != null)
        .sort(
          (left, right) =>
            (estimateDiyCost(right).usd ?? 0) - (estimateDiyCost(left).usd ?? 0),
        )
        .slice(0, 3),
    [telemetry],
  );
  const slowest = useMemo(
    () =>
      telemetry
        .filter((record) => record.latencyMs != null)
        .sort((left, right) => (right.latencyMs ?? 0) - (left.latencyMs ?? 0))
        .slice(0, 3),
    [telemetry],
  );
  const showCorrelation = useMemo(() => {
    if (developerMode) return true;
    const hostedSuccesses = telemetry.filter(
      (record) => record.engine === 'superdocs' && record.outcome === 'success',
    ).length;
    const diySuccesses = telemetry.filter(
      (record) => record.engine === 'diy' && record.outcome === 'success',
    ).length;
    return hostedSuccesses >= 5 && diySuccesses >= 5;
  }, [developerMode, telemetry]);
  const sessionBudgetExceeded =
    observabilitySettings.sessionBudgetUsd != null &&
    session.estimatedSpendCount > 0 &&
    session.estimatedSpend > observabilitySettings.sessionBudgetUsd;

  const handleExportCsv = () => {
    downloadText('telemetry-export.csv', telemetryCsv(telemetry), 'text/csv');
  };

  const handleExportJson = () =>
    downloadText(
      'telemetry-export.json',
      telemetryJson(filteredTelemetry),
      'application/json',
    );

  const handleExportMarkdown = () => {
    downloadText(
      'cost-context-report.md',
      telemetryMarkdown(filteredTelemetry, telemetry),
      'text/markdown',
    );
  };

  const handleClear = () => {
    if (shouldClearTelemetry(window.confirm)) {
      clearTelemetry();
    }
  };

  return (
    <div className="space-y-8 pb-8">
      {/* Toolbar */}
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <p className="text-muted-foreground text-sm max-w-2xl leading-relaxed">
          Everything the lab measures about cost, reliability, and context
          efficiency. SuperDocs abstracts token counts and time-to-first-token
          behind a hosted subscription, whereas DIY models expose exact unit
          economics.
        </p>
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <Button variant="outline" onClick={handleExportCsv} disabled={telemetry.length === 0} className="h-9" data-testid="button-export-telemetry-csv">
            <Download className="w-4 h-4 mr-2" />
            Export CSV
          </Button>
          <Button variant="outline" onClick={handleExportJson} disabled={telemetry.length === 0} className="h-9" data-testid="button-export-telemetry-json">
            <FileJson className="w-4 h-4 mr-2" />
            JSON
          </Button>
          <Button variant="outline" onClick={handleExportMarkdown} disabled={telemetry.length === 0} className="h-9" data-testid="button-export-telemetry-report">
            <FileText className="w-4 h-4 mr-2" />
            Report
          </Button>
          <Button variant="destructive" onClick={handleClear} disabled={telemetry.length === 0} className="h-9" data-testid="button-clear-telemetry">
            <Trash2 className="w-4 h-4 mr-2" />
            Clear Data
          </Button>
        </div>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="All-time Est. DIY Spend"
          value={spendLabel(allTime)}
          subValue={`${allTime.diyRequests} DIY requests · ${DIY_PRICING_VERSION}${allTime.unpricedDiyCount ? ` · ${allTime.unpricedDiyCount} pricing not configured` : ''}`}
          icon={Coins}
        />
        <StatCard
          title="All-time SuperDocs Activity"
          value={`${allTime.hostedRequests} reqs`}
          subValue={`${allTime.hostedUsageCount} usage values exposed · tokens/TTFT not exposed`}
          icon={Activity}
        />
        <StatCard
          title="All-time Reliability"
          value={`${allTime.requests ? ((allTime.successes/allTime.requests)*100).toFixed(1) : 0}%`}
          subValue={`${allTime.successes} of ${allTime.requests} succeeded · ${allTime.retries} retries`}
          icon={CheckCircle2}
        />
        <StatCard
          title="All-time Avg Latency"
          value={allTime.averageLatency != null ? `${Math.round(allTime.averageLatency)}ms` : 'Not measured'}
          subValue={`${allTime.contextChars.toLocaleString()} context chars sent`}
          icon={Clock}
        />
      </div>

      {sessionBudgetExceeded && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-950 dark:text-amber-200">
          <strong>Session budget warning:</strong> session DIY estimates total {formatUsd(session.estimatedSpend)}, above the configured ${observabilitySettings.sessionBudgetUsd?.toFixed(2)} warning threshold. Estimates only include models with local pricing configured.
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        {[
          ['This session', session, 'Requests made since this browser session began.'],
          ['Today', today, 'Local requests recorded since midnight.'],
          ['Benchmark focus', benchmark, 'Requests linked to reproducible benchmark runs.'],
        ].map(([label, metrics, note]) => {
          const summary = metrics as Metrics;
          return (
            <Card key={label as string} className="border-muted-foreground/15">
              <CardContent className="p-4">
                <div className="flex items-baseline justify-between gap-3">
                  <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{label as string}</p>
                  <span className="font-mono text-lg font-semibold">{summary.requests}</span>
                </div>
                <p className="mt-2 text-xs text-muted-foreground">{note as string}</p>
                <p className="mt-3 font-mono text-[11px]">
                  {summary.diyInputTokens.toLocaleString()} DIY input tokens · {spendLabel(summary)}
                </p>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {showCorrelation ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-1 h-full">
            <CorrelationCard telemetry={telemetry} />
          </div>
          <div className="lg:col-span-2">
            <BudgetControls />
          </div>
        </div>
      ) : (
        <BudgetControls />
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2 shadow-sm">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm uppercase tracking-wider text-primary">Engine efficiency</CardTitle>
            <CardDescription>Measured reliability, latency, and context volume; not an invented hosted cost comparison.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {(['diy', 'superdocs'] as const).map((engine) => {
              const engineMetrics = summarize(telemetry.filter((record) => record.engine === engine));
              const successRate = engineMetrics.requests
                ? (engineMetrics.successes / engineMetrics.requests) * 100
                : 0;
              return (
                <div key={engine} className="rounded-md border bg-muted/10 p-3">
                  <div className="flex items-center justify-between gap-4">
                    <p className="font-semibold">{engine === 'diy' ? 'DIY Toolkit' : 'SuperDocs hosted'}</p>
                    <p className="font-mono text-xs">{engineMetrics.requests} requests</p>
                  </div>
                  <div className="mt-3 h-2 overflow-hidden rounded-full bg-muted">
                    <div className="h-full rounded-full bg-primary" style={{ width: `${successRate}%` }} />
                  </div>
                  <div className="mt-2 grid grid-cols-3 gap-2 text-[11px] text-muted-foreground">
                    <span>{successRate.toFixed(0)}% success</span>
                    <span>{engineMetrics.averageLatency == null ? 'Latency not measured' : `${Math.round(engineMetrics.averageLatency)} ms avg`}</span>
                    <span>{engineMetrics.contextChars.toLocaleString()} chars sent</span>
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>
        <Card className="shadow-sm">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm uppercase tracking-wider text-primary">Decision economics</CardTitle>
            <CardDescription>Only explicit editor acceptance or rejection is counted.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 font-mono text-sm">
            <div className="flex justify-between"><span className="text-muted-foreground">Accepted</span><span>{allTime.accepted}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Rejected</span><span>{allTime.rejected}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Retries</span><span>{allTime.retries}</span></div>
            <div className="border-t pt-3 text-xs text-muted-foreground">Comparisons and benchmarks are intentionally not counted as accept/reject decisions.</div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card className="shadow-sm">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm uppercase tracking-wider text-primary">Most expensive DIY requests</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {mostExpensive.length ? mostExpensive.map((record) => (
              <div key={record.id} className="flex items-center justify-between rounded border bg-muted/10 px-3 py-2 text-xs">
                <span className="font-mono">{record.modelLabel} · {record.scope}</span>
                <span className="font-mono font-semibold">{formatUsd(estimateDiyCost(record).usd)}</span>
              </div>
            )) : <p className="py-4 text-sm text-muted-foreground">No priced DIY requests yet. Unknown models remain “Pricing not configured.”</p>}
          </CardContent>
        </Card>
        <Card className="shadow-sm">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm uppercase tracking-wider text-primary">Slowest measured requests</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {slowest.length ? slowest.map((record) => (
              <div key={record.id} className="flex items-center justify-between rounded border bg-muted/10 px-3 py-2 text-xs">
                <span className="font-mono">{record.engine} · {record.scope} · {record.outcome}</span>
                <span className="font-mono font-semibold">{record.latencyMs?.toLocaleString()} ms</span>
              </div>
            )) : <p className="py-4 text-sm text-muted-foreground">No measured latency yet.</p>}
          </CardContent>
        </Card>
      </div>

      {/* Telemetry Table */}
      <Card className="shadow-sm border-t-4 border-t-primary/60">
        <CardHeader className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b pb-4 bg-muted/10">
          <div>
            <CardTitle className="text-base text-primary uppercase tracking-wider">Request Telemetry</CardTitle>
            <CardDescription className="mt-1">Detailed breakdown of individual edits and benchmark cases.</CardDescription>
          </div>
          <div className="flex items-center gap-3">
            <Select
              value={engineFilter}
              onValueChange={(value) =>
                setEngineFilter(value as 'all' | 'diy' | 'superdocs')
              }
            >
              <SelectTrigger className="w-[140px] h-8 text-xs font-medium" data-testid="select-engine-filter">
                <SelectValue placeholder="All Engines" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Engines</SelectItem>
                <SelectItem value="diy">DIY Models</SelectItem>
                <SelectItem value="superdocs">SuperDocs</SelectItem>
              </SelectContent>
            </Select>
            <Select
              value={outcomeFilter}
              onValueChange={(value) =>
                setOutcomeFilter(value as 'all' | TelemetryRecord['outcome'])
              }
            >
              <SelectTrigger className="w-[140px] h-8 text-xs font-medium" data-testid="select-outcome-filter">
                <SelectValue placeholder="All Outcomes" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Outcomes</SelectItem>
                <SelectItem value="success">Success</SelectItem>
                <SelectItem value="error">Error</SelectItem>
                <SelectItem value="pending">Pending</SelectItem>
                <SelectItem value="cancelled">Cancelled</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="w-[160px] text-xs font-semibold uppercase tracking-wider">Timestamp</TableHead>
                  <TableHead className="text-xs font-semibold uppercase tracking-wider">Engine / Model</TableHead>
                  <TableHead className="text-xs font-semibold uppercase tracking-wider">Scope</TableHead>
                  <TableHead className="text-xs font-semibold uppercase tracking-wider">Context Config</TableHead>
                  <TableHead className="text-xs font-semibold uppercase tracking-wider">Latency</TableHead>
                  <TableHead className="text-xs font-semibold uppercase tracking-wider">Economics</TableHead>
                  <TableHead className="text-xs font-semibold uppercase tracking-wider">Outcome</TableHead>
                  <TableHead className="text-right text-xs font-semibold uppercase tracking-wider">Inspect</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredTelemetry.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8} className="h-48 text-center text-muted-foreground">
                      <div className="flex flex-col items-center justify-center gap-3">
                        <Database className="w-10 h-10 opacity-20" />
                        <p className="text-sm">No telemetry records match the current filters.</p>
                      </div>
                    </TableCell>
                  </TableRow>
                ) : (
                  filteredTelemetry.map(record => {
                    const est = estimateDiyCost(record);
                    return (
                      <TableRow key={record.id} className="hover:bg-muted/40 transition-colors group">
                        <TableCell className="text-[11px] font-mono text-muted-foreground whitespace-nowrap">
                          {format(new Date(record.createdAt), 'MMM d, HH:mm:ss')}
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-col gap-0.5">
                            <span className="font-semibold text-xs text-foreground uppercase tracking-wider">{record.engine}</span>
                            <span className="text-[10px] text-muted-foreground font-mono">{record.modelLabel}</span>
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className="text-[9px] font-semibold tracking-widest uppercase bg-background">
                            {record.scope}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-col text-[11px] font-mono">
                            <span className="text-foreground">{record.contextChars.toLocaleString()}c sent</span>
                            <span className="text-muted-foreground">{record.promptChars.toLocaleString()}c prompt</span>
                          </div>
                        </TableCell>
                        <TableCell className="text-[11px] font-mono">
                          {record.latencyMs != null
                            ? `${record.latencyMs}ms`
                            : 'Not measured'}
                        </TableCell>
                        <TableCell>
                          <div className="text-[11px] font-mono font-medium">
                            {record.engine === 'diy'
                              ? formatUsd(est.usd)
                              : record.usage.hostedUsage || 'Not exposed'}
                          </div>
                        </TableCell>
                        <TableCell>
                          {record.outcome === 'success' ? (
                            <div className="flex items-center text-emerald-600 dark:text-emerald-400 gap-1.5 text-xs font-medium">
                              <CheckCircle2 className="w-3.5 h-3.5" /> Success
                            </div>
                          ) : record.outcome === 'error' ? (
                            <div className="flex items-center text-destructive gap-1.5 text-xs font-medium">
                              <AlertCircle className="w-3.5 h-3.5" /> Error
                            </div>
                          ) : (
                            <div className="flex items-center text-muted-foreground gap-1.5 text-xs font-medium">
                              <Clock className="w-3.5 h-3.5" /> {record.outcome}
                            </div>
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          <RowDetailsDialog record={record} developerMode={developerMode}>
                            <Button variant="ghost" size="sm" className="h-7 text-[10px] uppercase tracking-wider font-semibold opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity" data-testid={`button-view-details-${record.id}`}>
                              View Details
                            </Button>
                          </RowDetailsDialog>
                        </TableCell>
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
