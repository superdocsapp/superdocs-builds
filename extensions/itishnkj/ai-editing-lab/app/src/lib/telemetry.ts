import type {
  EditInputEngine,
  EditInputScope,
  EditResult,
} from '@workspace/api-client-react';
import type { BenchmarkObservation } from './experiment';
import type { DocumentSourceType, ImportFormat } from './import/types';

export const TELEMETRY_SCHEMA_VERSION = 'telemetry-v2';
export const DIY_PRICING_VERSION = 'diy-pricing-2026-01';
export const DIY_PROMPT_VERSION = 'diy-selection-context-v2';
export const SUPERDOCS_PROMPT_VERSION = 'superdocs-hosted-v1';

export const CONTEXT_BUDGET_CHARS = 50_000;
export const CONTEXT_SOFT_BUDGET_CHARS = 30_000;
export const SELECTION_CONTEXT_LIMIT_CHARS = 12_000;

const DIY_SYSTEM_PROMPT = `You edit an existing professional rich-text document.
Obey the user's instruction exactly.
Preserve meaning unless the instruction says otherwise.
Preserve unrelated content and relevant HTML formatting.
Modify only the requested scope.
Return valid JSON and no markdown fences or commentary.
The JSON shape is: {"replacement_html":"<valid HTML>","explanation":"brief reason"}.
Never include scripts, iframes, event-handler attributes, or external embeds.`;

export type TelemetryOutcome =
  | 'pending'
  | 'success'
  | 'error'
  | 'cancelled';
export type DecisionState =
  | 'pending'
  | 'accepted'
  | 'rejected'
  | 'stopped'
  | 'not_applicable';
export type ContextStrategy =
  | 'full-document'
  | 'selection-with-nearby-structure'
  | 'full-document-for-reliability';
export type MetricState =
  | 'actual'
  | 'estimated'
  | 'not_exposed'
  | 'not_measured'
  | 'not_configured';

export type TelemetryUsage = {
  inputTokens: number | null;
  outputTokens: number | null;
  totalTokens: number | null;
  hostedUsage: string | null;
};

export type DocumentTelemetryMetadata = {
  documentId: string;
  documentSource: DocumentSourceType;
  fileType: ImportFormat | null;
  documentWordCount: number;
  documentCharacterCount: number;
};

export type TelemetryRecord = {
  id: string;
  schemaVersion: typeof TELEMETRY_SCHEMA_VERSION;
  createdAt: string;
  requestId: string;
  engine: EditInputEngine;
  modelLabel: string;
  promptVersion: string;
  promptChars: number;
  instructionChars: number;
  instructionFingerprint: string;
  scope: EditInputScope;
  documentChars: number;
  selectionChars: number;
  contextChars: number;
  outlineChars: number;
  nearbyStructureChars: number;
  contextStrategy: ContextStrategy;
  requestFingerprint: string;
  outcome: TelemetryOutcome;
  error: string | null;
  latencyMs: number | null;
  retryCount: number | null;
  usage: TelemetryUsage;
  usageState: MetricState;
  hostedUsageState: MetricState;
  decisionState: DecisionState;
  benchmarkRunId: string | null;
  benchmarkCaseId: string | null;
  compareRunId: string | null;
  duplicateOf: string | null;
  documentId?: string;
  documentSource?: DocumentSourceType;
  fileType?: ImportFormat | null;
  documentWordCount?: number;
  documentCharacterCount?: number;
};

export type TelemetrySettings = {
  sessionBudgetUsd: number | null;
  contextBudgetChars: number;
  softContextBudgetChars: number;
};

export const DEFAULT_TELEMETRY_SETTINGS: TelemetrySettings = {
  sessionBudgetUsd: null,
  contextBudgetChars: CONTEXT_BUDGET_CHARS,
  softContextBudgetChars: CONTEXT_SOFT_BUDGET_CHARS,
};

export type DiyPricing = {
  model: string;
  inputUsdPerMillion: number;
  outputUsdPerMillion: number;
};

// This table is deliberately local and versioned. Unknown models must remain
// visibly unpriced instead of being treated as free.
export const DIY_PRICING: DiyPricing[] = [
  { model: 'gpt-4o-mini', inputUsdPerMillion: 0.15, outputUsdPerMillion: 0.6 },
  { model: 'gpt-4o', inputUsdPerMillion: 2.5, outputUsdPerMillion: 10 },
  { model: 'gpt-4.1-mini', inputUsdPerMillion: 0.4, outputUsdPerMillion: 1.6 },
  { model: 'gpt-4.1', inputUsdPerMillion: 2, outputUsdPerMillion: 8 },
];

export type ContextEstimate = {
  strategy: ContextStrategy;
  contextChars: number;
  outlineChars: number;
  nearbyStructureChars: number;
  estimatedPromptChars: number;
  softExceeded: boolean;
  hardExceeded: boolean;
  note: string;
};

const FINGERPRINT_KEY_STORAGE = 'ai-editing-lab-telemetry-fingerprint-key-v1';
let ephemeralFingerprintKey: string | null = null;

function randomHex(bytes = 32): string {
  const values = crypto.getRandomValues(new Uint8Array(bytes));
  return Array.from(values, (value) => value.toString(16).padStart(2, '0')).join('');
}

function hexToBytes(hex: string): Uint8Array {
  return Uint8Array.from(
    hex.match(/.{1,2}/g) ?? [],
    (part) => Number.parseInt(part, 16),
  );
}

function fingerprintKey(): string {
  if (ephemeralFingerprintKey) return ephemeralFingerprintKey;
  try {
    const stored = localStorage.getItem(FINGERPRINT_KEY_STORAGE);
    if (stored) {
      ephemeralFingerprintKey = stored;
      return stored;
    }
    const generated = randomHex();
    localStorage.setItem(FINGERPRINT_KEY_STORAGE, generated);
    ephemeralFingerprintKey = generated;
    return generated;
  } catch {
    // Tests and non-browser runtimes receive an in-memory key. It is never
    // persisted in telemetry or included in an export.
    ephemeralFingerprintKey = randomHex();
    return ephemeralFingerprintKey;
  }
}

async function opaqueFingerprint(input: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    'raw',
    hexToBytes(fingerprintKey()).buffer as ArrayBuffer,
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  const signature = await crypto.subtle.sign(
    'HMAC',
    key,
    new TextEncoder().encode(input),
  );
  return `hmac-sha256-${Array.from(new Uint8Array(signature), (byte) =>
    byte.toString(16).padStart(2, '0'),
  ).join('')}`;
}

export function stripHtml(html: string): string {
  return html
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<[^>]*>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function outlineFromHtml(html: string): string {
  const headings = [...html.matchAll(/<h[1-6][^>]*>([\s\S]*?)<\/h[1-6]>/gi)]
    .map((match) => stripHtml(match[1] ?? ''))
    .filter(Boolean)
    .join(' · ');
  return headings.slice(0, 2_000);
}

function nearbyStructureFromHtml(
  documentHtml: string,
  selectionText: string,
): string {
  const documentText = stripHtml(documentHtml);
  const selected = stripHtml(selectionText);
  const position = selected ? documentText.indexOf(selected) : -1;
  if (position < 0) return documentText.slice(0, 800);
  return documentText.slice(
    Math.max(0, position - 600),
    Math.min(documentText.length, position + selected.length + 600),
  );
}

export function chooseContextStrategy(
  scope: EditInputScope,
  _documentChars: number,
  selectionChars: number,
): ContextStrategy {
  if (scope === 'document') return 'full-document';
  if (selectionChars > SELECTION_CONTEXT_LIMIT_CHARS) {
    return 'full-document-for-reliability';
  }
  return 'selection-with-nearby-structure';
}

type ContextInput = {
  documentHtml: string;
  selectionHtml?: string | null;
  selectionText?: string | null;
  scope: EditInputScope;
  instruction: string;
  contextBudgetChars?: number;
  softContextBudgetChars?: number;
};

function contextPlan(input: ContextInput) {
  const documentChars = input.documentHtml.length;
  const selected = input.selectionHtml || input.selectionText || '';
  const selectionTextForStructure = input.selectionText ?? selected;
  const selectionChars = stripHtml(selectionTextForStructure).length;
  const strategy = chooseContextStrategy(
    input.scope,
    documentChars,
    selectionChars,
  );
  const outline = outlineFromHtml(input.documentHtml);
  const nearby =
    input.scope === 'selection'
      ? nearbyStructureFromHtml(input.documentHtml, selectionTextForStructure)
      : '';
  const context =
    strategy === 'full-document' || strategy === 'full-document-for-reliability'
      ? input.documentHtml
      : [
          'SELECTED CONTENT:',
          selected,
          '',
          'DOCUMENT OUTLINE:',
          outline || '(no headings)',
          '',
          'NEARBY STRUCTURE (reference only; do not rewrite it):',
          nearby,
        ].join('\n');
  return { documentChars, selectionChars, strategy, outline, nearby, context };
}

function diyUserPrompt(
  scope: EditInputScope,
  instruction: string,
  context: string,
): string {
  return [
    `Prompt version: ${DIY_PROMPT_VERSION}`,
    `Scope: ${scope}`,
    `Instruction: ${instruction}`,
    '',
    scope === 'selection'
      ? 'CONTEXT TO EDIT (selected content is authoritative; nearby structure is reference only):'
      : 'CONTENT TO EDIT:',
    context,
    '',
    scope === 'selection'
      ? 'Return replacement HTML for only the selected content.'
      : 'Return the complete edited document HTML.',
  ].join('\n');
}

export function estimateContext(input: ContextInput): ContextEstimate {
  const plan = contextPlan(input);
  const contextChars = plan.context.length;
  // Only DIY replaces this with the exact initial-message character count in
  // estimateRequestContext. Hosted prompt construction is opaque, so retain
  // the measured context payload size rather than inventing a prompt total.
  const estimatedPromptChars = contextChars;
  const softBudget =
    input.softContextBudgetChars ?? CONTEXT_SOFT_BUDGET_CHARS;
  const hardBudget = input.contextBudgetChars ?? CONTEXT_BUDGET_CHARS;

  return {
    strategy: plan.strategy,
    contextChars,
    outlineChars:
      plan.strategy === 'selection-with-nearby-structure'
        ? plan.outline.length
        : 0,
    nearbyStructureChars:
      plan.strategy === 'selection-with-nearby-structure'
        ? plan.nearby.length
        : 0,
    estimatedPromptChars,
    softExceeded: contextChars > softBudget,
    hardExceeded: contextChars > hardBudget,
    note:
      plan.strategy === 'selection-with-nearby-structure'
        ? 'Selected content plus a bounded outline and nearby structure will be sent.'
        : plan.strategy === 'full-document-for-reliability'
          ? 'The full document is retained because the selected content is larger than the safe context threshold.'
          : 'The full document is required for a document-level edit.',
  };
}

export function estimateRequestContext(input: {
  engine: EditInputEngine;
  documentHtml: string;
  selectionHtml?: string | null;
  selectionText?: string | null;
  scope: EditInputScope;
  instruction: string;
  contextBudgetChars?: number;
  softContextBudgetChars?: number;
}): ContextEstimate {
  // The hosted review API receives document_html for every scope. Never report
  // its selection work as reduced context unless the provider payload changes.
  const estimate = estimateContext({
    ...input,
    selectionHtml: input.selectionHtml,
    scope: input.engine === 'superdocs' ? 'document' : input.scope,
  });
  if (input.engine !== 'diy') return estimate;

  const plan = contextPlan(input);
  return {
    ...estimate,
    estimatedPromptChars:
      DIY_SYSTEM_PROMPT.length +
      diyUserPrompt(input.scope, input.instruction, plan.context).length,
  };
}

export async function makeRequestFingerprint(input: {
  engine: EditInputEngine;
  documentHtml: string;
  selectionHtml?: string | null;
  selectionText?: string | null;
  scope: EditInputScope;
  instruction: string;
  preset?: string | null;
}): Promise<string> {
  return opaqueFingerprint(
    JSON.stringify({
      engine: input.engine,
      documentHtml: input.documentHtml,
      selectionHtml: input.selectionHtml ?? null,
      selectionText: input.selectionText ?? null,
      scope: input.scope,
      instruction: input.instruction.trim(),
      preset: input.preset ?? null,
    }),
  );
}

export async function createTelemetryDraft(input: {
  requestId: string;
  engine: EditInputEngine;
  modelLabel: string;
  documentHtml: string;
  selectionText?: string | null;
  scope: EditInputScope;
  instruction: string;
  selectionHtml?: string | null;
  preset?: string | null;
  benchmarkRunId?: string | null;
  benchmarkCaseId?: string | null;
  compareRunId?: string | null;
  settings?: TelemetrySettings;
  documentMetadata?: DocumentTelemetryMetadata;
}): Promise<Omit<TelemetryRecord, 'id' | 'createdAt'>> {
  const estimate = estimateRequestContext({
    engine: input.engine,
    documentHtml: input.documentHtml,
    selectionHtml: input.selectionHtml,
    selectionText: input.selectionText,
    scope: input.scope,
    instruction: input.instruction,
    contextBudgetChars: input.settings?.contextBudgetChars,
    softContextBudgetChars: input.settings?.softContextBudgetChars,
  });
  const usageState: MetricState =
    input.engine === 'diy' ? 'not_measured' : 'not_exposed';
  const documentPlainText = stripHtml(input.documentHtml);
  const documentMetadata: DocumentTelemetryMetadata = input.documentMetadata ?? {
    documentId: 'canonical-demo',
    documentSource: 'canonical',
    fileType: null,
    documentWordCount: documentPlainText
      ? documentPlainText.split(/\s+/).length
      : 0,
    documentCharacterCount: documentPlainText.length,
  };
  return {
    schemaVersion: TELEMETRY_SCHEMA_VERSION,
    requestId: input.requestId,
    engine: input.engine,
    modelLabel: input.modelLabel,
    promptVersion:
      input.engine === 'diy' ? DIY_PROMPT_VERSION : SUPERDOCS_PROMPT_VERSION,
    promptChars: estimate.estimatedPromptChars,
    instructionChars: input.instruction.length,
    instructionFingerprint: await opaqueFingerprint(input.instruction.trim()),
    scope: input.scope,
    documentChars: input.documentHtml.length,
    selectionChars: stripHtml(input.selectionText ?? input.selectionHtml ?? '').length,
    contextChars: estimate.contextChars,
    outlineChars: estimate.outlineChars,
    nearbyStructureChars: estimate.nearbyStructureChars,
    contextStrategy: estimate.strategy,
    requestFingerprint: await makeRequestFingerprint(input),
    outcome: 'pending',
    error: null,
    latencyMs: null,
    retryCount: null,
    usage: {
      inputTokens: null,
      outputTokens: null,
      totalTokens: null,
      hostedUsage: null,
    },
    usageState,
    hostedUsageState: input.engine === 'diy' ? 'not_exposed' : 'not_exposed',
    decisionState: 'pending',
    benchmarkRunId: input.benchmarkRunId ?? null,
    benchmarkCaseId: input.benchmarkCaseId ?? null,
    compareRunId: input.compareRunId ?? null,
    duplicateOf: null,
    ...documentMetadata,
  };
}

export function applyEditResult(
  draft: TelemetryRecord,
  result: EditResult,
): Partial<TelemetryRecord> {
  const hasUsage =
    result.usage?.inputTokens != null && result.usage.outputTokens != null;
  return {
    outcome: result.success ? 'success' : 'error',
    error: result.error ?? null,
    promptVersion: result.promptVersion,
    latencyMs: result.latencyMs,
    retryCount: result.retryCount,
    promptChars: result.requestMetrics.promptChars ?? draft.promptChars,
    contextChars: result.requestMetrics.contextChars,
    usage: {
      inputTokens: result.usage?.inputTokens ?? null,
      outputTokens: result.usage?.outputTokens ?? null,
      totalTokens: result.usage?.totalTokens ?? null,
      hostedUsage: result.usage?.hostedUsage ?? null,
    },
    usageState:
      draft.engine === 'diy'
        ? hasUsage
          ? 'actual'
          : 'not_exposed'
        : 'not_exposed',
    hostedUsageState:
      draft.engine === 'superdocs'
        ? result.usage?.hostedUsage
          ? 'actual'
          : 'not_exposed'
        : 'not_exposed',
  };
}

export function pricingForModel(modelLabel: string): DiyPricing | null {
  const model = modelLabel.trim().toLowerCase();
  return (
    DIY_PRICING.find(
      (pricing) =>
        model === pricing.model || model.startsWith(`${pricing.model}:`),
    ) ?? null
  );
}

export function estimateDiyCost(record: Pick<
  TelemetryRecord,
  'engine' | 'modelLabel' | 'usage'
>): { state: MetricState; usd: number | null; label: string } {
  if (record.engine !== 'diy') {
    return { state: 'not_exposed', usd: null, label: 'Not applicable' };
  }
  const pricing = pricingForModel(record.modelLabel);
  if (!pricing) {
    return { state: 'not_configured', usd: null, label: 'Pricing not configured' };
  }
  if (
    record.usage.inputTokens == null ||
    record.usage.outputTokens == null
  ) {
    return { state: 'not_measured', usd: null, label: 'Not measured' };
  }
  const usd =
    (record.usage.inputTokens / 1_000_000) * pricing.inputUsdPerMillion +
    (record.usage.outputTokens / 1_000_000) * pricing.outputUsdPerMillion;
  return { state: 'estimated', usd, label: 'Estimated' };
}

export function estimateDiyPreflightCost(
  modelLabel: string,
  promptChars: number,
): {
  state: MetricState;
  usd: number | null;
  estimatedInputTokens: number | null;
  estimatedOutputTokens: number | null;
} {
  const pricing = pricingForModel(modelLabel);
  if (!pricing) {
    return {
      state: 'not_configured',
      usd: null,
      estimatedInputTokens: null,
      estimatedOutputTokens: null,
    };
  }
  // This is intentionally a visible planning heuristic, never a substitute for
  // the provider's actual token usage persisted after the request finishes.
  const estimatedInputTokens = Math.ceil(promptChars / 4);
  const estimatedOutputTokens = Math.ceil(estimatedInputTokens * 0.3);
  return {
    state: 'estimated',
    estimatedInputTokens,
    estimatedOutputTokens,
    usd:
      (estimatedInputTokens / 1_000_000) * pricing.inputUsdPerMillion +
      (estimatedOutputTokens / 1_000_000) * pricing.outputUsdPerMillion,
  };
}

export function formatMetric(value: number | null, suffix = ''): string {
  return value == null ? 'Not exposed' : `${value.toLocaleString()}${suffix}`;
}

export function formatUsd(value: number | null): string {
  return value == null ? 'Pricing not configured' : `$${value.toFixed(4)}`;
}

export function telemetryFromBenchmarkObservation(
  observation: BenchmarkObservation,
  modelLabel: string,
): Partial<TelemetryRecord> {
  return {
    outcome: observation.success ? 'success' : 'error',
    error: observation.error,
    latencyMs: observation.latencyMs,
    retryCount: observation.retryCount,
    usage: {
      inputTokens: observation.inputTokens,
      outputTokens: observation.outputTokens,
      totalTokens: observation.totalTokens,
      hostedUsage: observation.hostedUsage,
    },
    modelLabel,
    usageState:
      observation.engine === 'diy' && observation.totalTokens != null
        ? 'actual'
        : 'not_exposed',
    hostedUsageState:
      observation.engine === 'superdocs' && observation.hostedUsage
        ? 'actual'
        : 'not_exposed',
  };
}