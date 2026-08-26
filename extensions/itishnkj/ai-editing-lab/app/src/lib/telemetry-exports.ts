import { csvCell } from './experiment';
import {
  DIY_PRICING_VERSION,
  estimateDiyCost,
  TELEMETRY_SCHEMA_VERSION,
  type TelemetryRecord,
} from './telemetry';

export const CLEAR_TELEMETRY_CONFIRMATION =
  'Clear all locally persisted Cost & Context telemetry? This keeps your document, versions, comparisons, and benchmarks.';

export function shouldClearTelemetry(
  confirm: (message: string) => boolean,
): boolean {
  return confirm(CLEAR_TELEMETRY_CONFIRMATION);
}

export function telemetryCsv(records: TelemetryRecord[]): string {
  const headers = [
    'ID', 'Timestamp', 'Engine', 'Model', 'Scope', 'Outcome',
    'Latency (ms)', 'Context Strategy', 'Document Chars', 'Selection Chars', 'Context Chars',
    'Prompt Chars', 'Input Tokens', 'Output Tokens', 'Total Tokens',
    'Hosted Usage', 'Est. DIY Cost (USD)', 'Cost State', 'Decision', 'Document ID', 'Document Source', 'File Type', 'Document Words', 'Document Characters', 'Benchmark Run', 'Error', 'Opaque Request Fingerprint',
  ];
  const rows = records.map((record) => {
    const estimate = estimateDiyCost(record);
    return [
      record.id,
      new Date(record.createdAt).toISOString(),
      record.engine,
      record.modelLabel,
      record.scope,
      record.outcome,
      record.latencyMs ?? '',
      record.contextStrategy,
      record.documentChars,
      record.selectionChars,
      record.contextChars,
      record.promptChars,
      record.usage.inputTokens ?? '',
      record.usage.outputTokens ?? '',
      record.usage.totalTokens ?? '',
      record.usage.hostedUsage ?? '',
      estimate.usd ?? '',
      estimate.state,
      record.decisionState,
      record.documentId ?? '',
      record.documentSource ?? 'canonical',
      record.fileType ?? '',
      record.documentWordCount ?? '',
      record.documentCharacterCount ?? record.documentChars,
      record.benchmarkRunId ?? '',
      record.error ?? '',
      record.requestFingerprint,
    ].map(csvCell).join(',');
  });
  return [headers.map(csvCell).join(','), ...rows].join('\n');
}

export function telemetryJson(records: TelemetryRecord[]): string {
  return JSON.stringify(
    {
      telemetrySchemaVersion: TELEMETRY_SCHEMA_VERSION,
      pricingVersion: DIY_PRICING_VERSION,
      records,
    },
    null,
    2,
  );
}

export function telemetryMarkdown(
  records: TelemetryRecord[],
  summaryRecords: TelemetryRecord[] = records,
): string {
  const diyRecords = summaryRecords.filter((record) => record.engine === 'diy');
  const pricedDiy = diyRecords
    .map(estimateDiyCost)
    .filter(
      (estimate): estimate is { usd: number; state: 'estimated'; label: string } =>
        estimate.state === 'estimated' && estimate.usd != null,
    );
  const totalDiySpend = pricedDiy.reduce((sum, estimate) => sum + estimate.usd, 0);
  const inputTokens = diyRecords.reduce(
    (sum, record) => sum + (record.usage.inputTokens ?? 0),
    0,
  );
  const outputTokens = diyRecords.reduce(
    (sum, record) => sum + (record.usage.outputTokens ?? 0),
    0,
  );
  const unpricedDiyCount = diyRecords.filter(
    (record) => estimateDiyCost(record).state === 'not_configured',
  ).length;
  const retries = summaryRecords.reduce(
    (sum, record) => sum + (record.retryCount ?? 0),
    0,
  );
  const latency = summaryRecords
    .map((record) => record.latencyMs)
    .filter((value): value is number => value != null);
  const averageLatency = latency.length
    ? Math.round(latency.reduce((sum, value) => sum + value, 0) / latency.length)
    : null;
  const rows = records
    .map(
      (record) =>
        `| ${record.createdAt} | ${record.engine} | ${record.scope} | ${record.outcome} | ${record.latencyMs ?? 'Not measured'} | ${record.contextChars} | ${record.engine === 'diy' ? (estimateDiyCost(record).usd == null ? 'Pricing not configured' : `$${estimateDiyCost(record).usd?.toFixed(4)}`) : 'Not exposed'} |`,
    )
    .join('\n');

  return `# Cost & Context Report

- Telemetry schema: ${TELEMETRY_SCHEMA_VERSION}
- DIY pricing configuration: ${DIY_PRICING_VERSION}
- Total requests: ${summaryRecords.length}
- DIY actual tokens: ${inputTokens.toLocaleString()} input / ${outputTokens.toLocaleString()} output
- DIY spend: ${pricedDiy.length ? `$${totalDiySpend.toFixed(4)}` : unpricedDiyCount ? 'Pricing not configured' : 'Not measured'}
- SuperDocs hosted usage exposed: ${summaryRecords.filter((record) => record.engine === 'superdocs' && record.usage.hostedUsage).length} request(s)
- SuperDocs raw model tokens, direct model cost, and TTFT: Not exposed / Not measured
- Average measured latency: ${averageLatency == null ? 'Not measured' : `${averageLatency} ms`}
- Retry count: ${retries}
- Acceptance economics: ${summaryRecords.filter((record) => record.decisionState === 'accepted').length} accepted / ${summaryRecords.filter((record) => record.decisionState === 'rejected').length} rejected
- Context sent: ${summaryRecords.reduce((sum, record) => sum + record.contextChars, 0).toLocaleString()} characters

## Requests

| Timestamp | Engine | Scope | Outcome | Latency ms | Context chars | DIY estimated cost |
| --- | --- | --- | --- | ---: | ---: | --- |
${rows || '| No records | - | - | - | - | - | - |'}
`;
}