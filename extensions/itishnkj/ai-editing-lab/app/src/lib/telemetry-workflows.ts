import type {
  EditInput,
  EditInputEngine,
} from '@workspace/api-client-react';
import {
  createTelemetryDraft,
  type ContextEstimate,
  type DocumentTelemetryMetadata,
  type TelemetryRecord,
  type TelemetrySettings,
} from './telemetry';

export type EditRequestPolicy = {
  engine: EditInputEngine;
  documentHtml: string;
  selectionHtml?: string | null;
  selectionText?: string | null;
  selectionFrom?: number | null;
  selectionTo?: number | null;
  scope: EditInput['scope'];
  instruction: string;
  preset?: string | null;
  requestId: string;
  currentVersionId: string;
};

export type TelemetryRequestLink = Pick<
  TelemetryRecord,
  'benchmarkRunId' | 'benchmarkCaseId' | 'compareRunId'
>;

export type ContextLimitAction = 'allow' | 'confirm' | 'block';

/**
 * Produces the exact browser-to-API contract. Telemetry derives from this
 * output, rather than duplicating its scope and selection rules.
 */
export function buildEditRequest(policy: EditRequestPolicy): EditInput {
  const isSelection = policy.scope === 'selection';
  return {
    engine: policy.engine,
    documentHtml: policy.documentHtml,
    selectionHtml: isSelection ? policy.selectionHtml ?? null : null,
    selectionText: isSelection ? policy.selectionText ?? null : null,
    selectionFrom: isSelection ? policy.selectionFrom ?? null : null,
    selectionTo: isSelection ? policy.selectionTo ?? null : null,
    scope: policy.scope,
    instruction: policy.instruction,
    preset: policy.preset ?? null,
    requestId: policy.requestId,
    currentVersionId: policy.currentVersionId,
  };
}

/**
 * Uses the same normalized request object that is sent to the API, keeping
 * recorded context strategy and character counts tied to provider policy.
 */
export function createTelemetryDraftForRequest(input: {
  request: EditInput;
  modelLabel: string;
  settings?: TelemetrySettings;
  link?: Partial<TelemetryRequestLink>;
  documentMetadata?: DocumentTelemetryMetadata;
}): Promise<Omit<TelemetryRecord, 'id' | 'createdAt'>> {
  const { request, link, modelLabel, settings, documentMetadata } = input;
  return createTelemetryDraft({
    requestId: request.requestId,
    engine: request.engine,
    modelLabel,
    documentHtml: request.documentHtml,
    selectionHtml: request.selectionHtml,
    selectionText: request.selectionText,
    scope: request.scope,
    instruction: request.instruction,
    preset: request.preset,
    benchmarkRunId: link?.benchmarkRunId,
    benchmarkCaseId: link?.benchmarkCaseId,
    compareRunId: link?.compareRunId,
    settings,
    documentMetadata,
  });
}

export function contextLimitAction(
  estimate: Pick<ContextEstimate, 'hardExceeded' | 'softExceeded'>,
): ContextLimitAction {
  if (estimate.hardExceeded) return 'block';
  if (estimate.softExceeded) return 'confirm';
  return 'allow';
}