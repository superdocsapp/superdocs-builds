import { useMemo } from 'react';
import { Link } from 'wouter';
import {
  CheckCircle2,
  Clock,
  FileText,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { estimateDiyCost, formatUsd } from '@/lib/telemetry';
import type { TelemetryRecord } from '@/lib/telemetry';
import { useLabStore } from '@/lib/store';

function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2;
}

type EngineSummary = {
  requests: number;
  successRate: number | null;
  medianLatencyMs: number | null;
  accepted: number;
  rejected: number;
  spendUsd: number | null;
};

function summarizeEngine(records: TelemetryRecord[]): EngineSummary {
  const successes = records.filter((record) => record.outcome === 'success');
  const accepted = records.filter(
    (record) => record.decisionState === 'accepted',
  ).length;
  const rejected = records.filter(
    (record) => record.decisionState === 'rejected',
  ).length;
  let spend: number | null = null;
  records.forEach((record) => {
    const estimate = estimateDiyCost(record);
    if (estimate.usd != null) spend = (spend ?? 0) + estimate.usd;
  });
  return {
    requests: records.length,
    successRate: records.length ? successes.length / records.length : null,
    medianLatencyMs: median(
      records
        .map((record) => record.latencyMs)
        .filter((value): value is number => value != null),
    ),
    accepted,
    rejected,
    spendUsd: spend,
  };
}

function StatTile({
  icon: Icon,
  label,
  value,
  hint,
  testId,
}: {
  icon: typeof FileText;
  label: string;
  value: string;
  hint: string;
  testId: string;
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center gap-2 text-muted-foreground">
          <Icon className="h-4 w-4" />
          <p className="text-xs font-medium">{label}</p>
        </div>
        <p className="mt-2 text-2xl font-semibold tracking-tight" data-testid={testId}>
          {value}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
      </CardContent>
    </Card>
  );
}

export function OverviewTab() {
  const { telemetry, editEvents, versions, documentSession } = useLabStore();

  const documentsEdited = useMemo(() => {
    const ids = new Set(editEvents.map((event) => event.documentId));
    if (versions.length > 1) ids.add(documentSession.id);
    return ids.size;
  }, [documentSession.id, editEvents, versions.length]);

  const accepted = telemetry.filter(
    (record) => record.decisionState === 'accepted',
  ).length;
  const rejected = telemetry.filter(
    (record) => record.decisionState === 'rejected',
  ).length;
  const medianLatency = median(
    telemetry
      .map((record) => record.latencyMs)
      .filter((value): value is number => value != null),
  );

  const diy = useMemo(
    () => summarizeEngine(telemetry.filter((record) => record.engine === 'diy')),
    [telemetry],
  );
  const superdocs = useMemo(
    () =>
      summarizeEngine(
        telemetry.filter((record) => record.engine === 'superdocs'),
      ),
    [telemetry],
  );

  if (telemetry.length === 0 && editEvents.length === 0) {
    return (
      <div className="flex flex-col items-center rounded-lg border border-dashed py-16 text-center">
        <Sparkles className="h-8 w-8 text-muted-foreground" />
        <p className="mt-3 text-sm font-medium">Nothing to summarize yet</p>
        <p className="mt-1 max-w-sm text-xs text-muted-foreground">
          Once you ask the assistant for edits, this page shows how the two
          engines are performing for you — in plain language, with full detail
          in the other tabs.
        </p>
        <Button className="mt-4" asChild>
          <Link href="/" data-testid="button-overview-go-editor">
            Open the editor
          </Link>
        </Button>
      </div>
    );
  }

  const comparisonRows: Array<{
    label: string;
    diyValue: string;
    superdocsValue: string;
  }> = [
    {
      label: 'Requests',
      diyValue: String(diy.requests),
      superdocsValue: String(superdocs.requests),
    },
    {
      label: 'Completed successfully',
      diyValue:
        diy.successRate == null ? '—' : `${Math.round(diy.successRate * 100)}%`,
      superdocsValue:
        superdocs.successRate == null
          ? '—'
          : `${Math.round(superdocs.successRate * 100)}%`,
    },
    {
      label: 'Typical response time',
      diyValue:
        diy.medianLatencyMs == null
          ? '—'
          : `${(diy.medianLatencyMs / 1000).toFixed(1)}s`,
      superdocsValue:
        superdocs.medianLatencyMs == null
          ? '—'
          : `${(superdocs.medianLatencyMs / 1000).toFixed(1)}s`,
    },
    {
      label: 'Suggestions you accepted',
      diyValue: `${diy.accepted}${diy.accepted + diy.rejected ? ` of ${diy.accepted + diy.rejected} decided` : ''}`,
      superdocsValue: `${superdocs.accepted}${
        superdocs.accepted + superdocs.rejected
          ? ` of ${superdocs.accepted + superdocs.rejected} decided`
          : ''
      }`,
    },
    {
      label: 'Estimated cost',
      diyValue: diy.spendUsd == null ? 'Not priced' : formatUsd(diy.spendUsd),
      superdocsValue: 'Not disclosed by the service',
    },
  ];

  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          icon={FileText}
          label="Documents edited"
          value={String(documentsEdited)}
          hint="Documents with at least one reviewed suggestion"
          testId="stat-documents-edited"
        />
        <StatTile
          icon={ThumbsUp}
          label="Suggestions accepted"
          value={String(accepted)}
          hint="Each one became a document version"
          testId="stat-suggestions-accepted"
        />
        <StatTile
          icon={ThumbsDown}
          label="Suggestions rejected"
          value={String(rejected)}
          hint="Rejected suggestions never touch your document"
          testId="stat-suggestions-rejected"
        />
        <StatTile
          icon={Clock}
          label="Typical response time"
          value={
            medianLatency == null ? '—' : `${(medianLatency / 1000).toFixed(1)}s`
          }
          hint="Median across all edit requests"
          testId="stat-median-latency"
        />
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">DIY vs SuperDocs, at a glance</CardTitle>
          <CardDescription>
            A plain-language comparison of your own usage. The Cost &amp; Context
            tab has the complete measurements behind these numbers.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-hidden rounded-md border">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium"> </th>
                  <th className="px-3 py-2 font-medium">DIY</th>
                  <th className="px-3 py-2 font-medium">SuperDocs</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {comparisonRows.map((row) => (
                  <tr key={row.label}>
                    <td className="px-3 py-2.5 text-muted-foreground">{row.label}</td>
                    <td className="px-3 py-2.5 font-medium">{row.diyValue}</td>
                    <td className="px-3 py-2.5 font-medium">{row.superdocsValue}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 flex items-start gap-1.5 text-xs text-muted-foreground">
            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            Costs shown are estimates for DIY models with configured pricing.
            SuperDocs does not expose token counts or per-request costs.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
