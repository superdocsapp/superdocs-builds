import assert from 'node:assert/strict';
import test from 'node:test';
import type { EditInput, EditResult } from '@workspace/api-client-react';
import { BENCHMARK_CASES, INITIAL_DOCUMENT_HTML } from '../src/lib/constants.ts';
import {
  CLEAR_TELEMETRY_CONFIRMATION,
  shouldClearTelemetry,
  telemetryCsv,
  telemetryJson,
  telemetryMarkdown,
} from '../src/lib/telemetry-exports.ts';
import {
  applyEditResult,
  estimateRequestContext,
  type TelemetryRecord,
} from '../src/lib/telemetry.ts';
import {
  buildEditRequest,
  contextLimitAction,
  createTelemetryDraftForRequest,
} from '../src/lib/telemetry-workflows.ts';
import { installMockLabApi } from '../src/lib/mock-lab-api.ts';

function benchmarkTarget(chunkId: string): { html: string; text: string } | null {
  const escapedChunkId = chunkId.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = INITIAL_DOCUMENT_HTML.match(
    new RegExp(
      `<([a-z0-9]+)[^>]*data-chunk-id="${escapedChunkId}"[^>]*>[\\s\\S]*?</\\1>`,
      'i',
    ),
  );
  if (!match) return null;
  return {
    html: match[0],
    text: match[0].replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim(),
  };
}

function mockedProviders() {
  const calls: EditInput[] = [];

  return {
    calls,
    async request(input: EditInput): Promise<EditResult> {
      calls.push(input);
      const estimate = estimateRequestContext({
        engine: input.engine,
        documentHtml: input.documentHtml,
        selectionHtml: input.selectionHtml,
        selectionText: input.selectionText,
        scope: input.scope,
        instruction: input.instruction,
      });
      return {
        engine: input.engine,
        engineLabel: input.engine === 'diy' ? 'DIY Toolkit' : 'SuperDocs Hosted',
        promptVersion:
          input.engine === 'diy'
            ? 'diy-selection-context-v2'
            : 'superdocs-hosted-v1',
        requestId: input.requestId,
        success: true,
        proposedChanges: [],
        candidateDocumentHtml: null,
        assistantMessage: 'Mocked provider proposal',
        latencyMs: 12,
        reviewWaitMs: null,
        usage:
          input.engine === 'diy'
            ? {
                inputTokens: 10,
                outputTokens: 5,
                totalTokens: 15,
                hostedUsage: null,
              }
            : {
                inputTokens: null,
                outputTokens: null,
                totalTokens: null,
                hostedUsage: '{"credits":1}',
              },
        retryCount: 0,
        requestMetrics: {
          promptChars:
            input.engine === 'diy' ? estimate.estimatedPromptChars : null,
          contextChars: estimate.contextChars,
        },
        error: null,
        review: null,
        startedAt: '2026-08-21T00:00:00.000Z',
        completedAt: '2026-08-21T00:00:00.012Z',
      };
    },
  };
}

async function runAndRecord(request: EditInput, provider: ReturnType<typeof mockedProviders>) {
  const draft = await createTelemetryDraftForRequest({
    request,
    modelLabel: request.engine === 'diy' ? 'gpt-4o-mini' : 'core · balanced',
  });
  const result = await provider.request(request);
  return {
    request,
    result,
    record: {
      ...draft,
      id: `telemetry-${request.engine}-${request.requestId}`,
      createdAt: '2026-08-21T00:00:00.000Z',
    },
    patch: applyEditResult(
      {
        ...draft,
        id: `telemetry-${request.engine}-${request.requestId}`,
        createdAt: '2026-08-21T00:00:00.000Z',
      },
      result,
    ),
  };
}

function assertRecordedContextMatchesProvider(
  run: Awaited<ReturnType<typeof runAndRecord>>,
) {
  assert.equal(run.patch.contextChars, run.result.requestMetrics.contextChars);
  assert.equal(
    run.patch.promptChars,
    run.result.requestMetrics.promptChars ?? run.record.promptChars,
  );
  assert.equal(run.record.documentChars, run.request.documentHtml.length);
}

test('mocked editor requests keep DIY selection and SuperDocs full-document telemetry aligned', async () => {
  const provider = mockedProviders();
  const documentHtml =
    `<h1>Context</h1>${'<p>Filler document text.</p>'.repeat(120)}` +
    '<p><strong>Selected sentence.</strong></p>';
  const selectionHtml = '<p><strong>Selected sentence.</strong></p>';
  const selectionText = 'Selected sentence.';
  const requests = (['diy', 'superdocs'] as const).map((engine) =>
    buildEditRequest({
      engine,
      documentHtml,
      selectionHtml,
      selectionText,
      selectionFrom: 8,
      selectionTo: 26,
      scope: 'selection',
      instruction: 'Clarify the selected sentence',
      requestId: `editor-${engine}`,
      currentVersionId: 'editor-version',
    }),
  );
  const runs = await Promise.all(requests.map((request) => runAndRecord(request, provider)));

  assert.deepEqual(
    [...provider.calls].sort((left, right) =>
      left.requestId.localeCompare(right.requestId),
    ),
    [...requests].sort((left, right) =>
      left.requestId.localeCompare(right.requestId),
    ),
  );
  for (const run of runs) assertRecordedContextMatchesProvider(run);
  assert.equal(runs[0].record.contextStrategy, 'selection-with-nearby-structure');
  assert.ok(runs[0].record.contextChars < documentHtml.length);
  assert.equal(runs[1].record.contextStrategy, 'full-document');
  assert.equal(runs[1].record.contextChars, documentHtml.length);
  assert.equal(runs[1].request.selectionHtml, selectionHtml);
  assert.equal(runs[1].request.documentHtml, documentHtml);
});

test('mocked comparison requests share one full-document payload and telemetry policy', async () => {
  const provider = mockedProviders();
  const requestId = 'compare-request';
  const requests = (['diy', 'superdocs'] as const).map((engine) =>
    buildEditRequest({
      engine,
      documentHtml: INITIAL_DOCUMENT_HTML,
      scope: 'document',
      instruction: 'Make the executive summary more concise.',
      requestId,
      currentVersionId: 'compare-version',
    }),
  );
  const runs = await Promise.all(requests.map((request) => runAndRecord(request, provider)));

  assert.deepEqual(
    [...provider.calls].sort((left, right) => left.engine.localeCompare(right.engine)),
    [...requests].sort((left, right) => left.engine.localeCompare(right.engine)),
  );
  assert.equal(runs[0].request.requestId, runs[1].request.requestId);
  assert.equal(runs[0].request.documentHtml, runs[1].request.documentHtml);
  for (const run of runs) {
    assertRecordedContextMatchesProvider(run);
    assert.equal(run.record.contextStrategy, 'full-document');
    assert.equal(run.record.contextChars, INITIAL_DOCUMENT_HTML.length);
    assert.equal(run.request.selectionHtml, null);
    assert.equal(run.request.selectionText, null);
  }
});

test('mocked benchmark requests preserve each case payload policy for both engines', async () => {
  const provider = mockedProviders();
  const benchmarkRunId = 'benchmark-run';
  const requests = BENCHMARK_CASES.flatMap((testCase) => {
    const target = testCase.targetChunkId
      ? benchmarkTarget(testCase.targetChunkId)
      : null;
    return (['diy', 'superdocs'] as const).map((engine) =>
      buildEditRequest({
        engine,
        documentHtml: INITIAL_DOCUMENT_HTML,
        selectionHtml: testCase.scope === 'selection' ? target?.html ?? null : null,
        selectionText: testCase.scope === 'selection' ? target?.text ?? null : null,
        selectionFrom: null,
        selectionTo: null,
        scope: testCase.scope,
        instruction: testCase.instruction,
        preset: testCase.label,
        requestId: `${benchmarkRunId}-${testCase.id}-${engine}`,
        currentVersionId: benchmarkRunId,
      }),
    );
  });
  const runs = await Promise.all(requests.map((request) => runAndRecord(request, provider)));

  assert.equal(provider.calls.length, BENCHMARK_CASES.length * 2);
  assert.deepEqual(
    [...provider.calls].sort((left, right) =>
      left.requestId.localeCompare(right.requestId),
    ),
    [...requests].sort((left, right) =>
      left.requestId.localeCompare(right.requestId),
    ),
  );
  for (const run of runs) {
    assertRecordedContextMatchesProvider(run);
    assert.equal(run.request.currentVersionId, benchmarkRunId);
    assert.ok(run.request.preset);
    if (run.request.engine === 'superdocs') {
      assert.equal(run.record.contextStrategy, 'full-document');
      assert.equal(run.record.contextChars, INITIAL_DOCUMENT_HTML.length);
    }
  }
  assert.ok(
    runs.some(
      (run) =>
        run.request.engine === 'diy' &&
        run.request.scope === 'selection' &&
        run.record.contextStrategy === 'selection-with-nearby-structure',
    ),
  );
});

test('hard limits block and soft limits require confirmation for editor, comparison, and benchmark policies', () => {
  const editorEstimate = estimateRequestContext({
    engine: 'diy',
    documentHtml: '<p>Editor payload</p>',
    selectionHtml: '<p>payload</p>',
    selectionText: 'payload',
    scope: 'selection',
    instruction: 'Improve',
    contextBudgetChars: 1,
    softContextBudgetChars: 0,
  });
  const compareEstimate = estimateRequestContext({
    engine: 'superdocs',
    documentHtml: INITIAL_DOCUMENT_HTML,
    scope: 'document',
    instruction: 'Improve',
    contextBudgetChars: 1,
    softContextBudgetChars: 0,
  });
  const benchmarkEstimate = estimateRequestContext({
    engine: 'superdocs',
    documentHtml: INITIAL_DOCUMENT_HTML,
    scope: 'selection',
    instruction: BENCHMARK_CASES[0].instruction,
    contextBudgetChars: 1,
    softContextBudgetChars: 0,
  });
  for (const estimate of [editorEstimate, compareEstimate, benchmarkEstimate]) {
    assert.equal(contextLimitAction(estimate), 'block');
  }

  const softOnly = [editorEstimate, compareEstimate, benchmarkEstimate].map(
    (estimate) =>
      estimateRequestContext({
        engine: estimate === editorEstimate ? 'diy' : 'superdocs',
        documentHtml:
          estimate === editorEstimate ? '<p>Editor payload</p>' : INITIAL_DOCUMENT_HTML,
        selectionHtml:
          estimate === editorEstimate ? '<p>payload</p>' : undefined,
        selectionText: estimate === editorEstimate ? 'payload' : undefined,
        scope: estimate === editorEstimate ? 'selection' : 'document',
        instruction:
          estimate === benchmarkEstimate
            ? BENCHMARK_CASES[0].instruction
            : 'Improve',
        contextBudgetChars: 100_000,
        softContextBudgetChars: 1,
      }),
  );
  for (const estimate of softOnly) {
    assert.equal(contextLimitAction(estimate), 'confirm');
  }
  assert.equal(
    contextLimitAction({ hardExceeded: false, softExceeded: false }),
    'allow',
  );
});

function seededRecord(
  engine: TelemetryRecord['engine'],
  id: string,
): TelemetryRecord {
  return {
    id,
    schemaVersion: 'telemetry-v2',
    createdAt: '2026-08-21T00:00:00.000Z',
    requestId: `${id}-request`,
    engine,
    modelLabel: engine === 'diy' ? 'gpt-4o-mini' : 'core · balanced',
    promptVersion: engine === 'diy' ? 'diy-selection-context-v2' : 'superdocs-hosted-v1',
    promptChars: 123,
    instructionChars: 18,
    instructionFingerprint: `hmac-sha256-${id}-instruction`,
    scope: 'document',
    documentChars: 98,
    selectionChars: 0,
    contextChars: 98,
    outlineChars: 0,
    nearbyStructureChars: 0,
    contextStrategy: 'full-document',
    requestFingerprint: `hmac-sha256-${id}-request`,
    outcome: 'success',
    error: null,
    latencyMs: 42,
    retryCount: 0,
    usage:
      engine === 'diy'
        ? { inputTokens: 20, outputTokens: 10, totalTokens: 30, hostedUsage: null }
        : {
            inputTokens: null,
            outputTokens: null,
            totalTokens: null,
            hostedUsage: '{"credits":1}',
          },
    usageState: engine === 'diy' ? 'actual' : 'not_exposed',
    hostedUsageState: engine === 'superdocs' ? 'actual' : 'not_exposed',
    decisionState: 'not_applicable',
    benchmarkRunId: null,
    benchmarkCaseId: null,
    compareRunId: null,
    duplicateOf: null,
  };
}

test('seeded local telemetry supports request detail, all exports, and explicit clearing confirmation', () => {
  const records = [seededRecord('diy', 'seed-diy'), seededRecord('superdocs', 'seed-hosted')];
  const requestDetail = records[1];
  assert.equal(requestDetail.contextStrategy, 'full-document');
  assert.equal(requestDetail.contextChars, requestDetail.documentChars);
  assert.equal(requestDetail.usage.hostedUsage, '{"credits":1}');

  const csv = telemetryCsv(records);
  const json = telemetryJson(records);
  const markdown = telemetryMarkdown(records);
  assert.match(csv, /Context Strategy/);
  assert.match(csv, /seed-diy/);
  assert.match(csv, /seed-hosted/);
  assert.deepEqual(JSON.parse(json).records, records);
  assert.match(markdown, /Total requests: 2/);
  assert.match(markdown, /SuperDocs raw model tokens, direct model cost, and TTFT/);
  assert.match(markdown, /Acceptance economics: 0 accepted \/ 0 rejected/);
  const filteredMarkdown = telemetryMarkdown([records[1]], records);
  assert.match(filteredMarkdown, /Total requests: 2/);
  assert.match(filteredMarkdown, /^\| .* \| superdocs \|/m);
  assert.doesNotMatch(filteredMarkdown, /^\| .* \| diy \|/m);

  const confirmationMessages: string[] = [];
  assert.equal(
    shouldClearTelemetry((message) => {
      confirmationMessages.push(message);
      return false;
    }),
    false,
  );
  assert.deepEqual(confirmationMessages, [CLEAR_TELEMETRY_CONFIRMATION]);
  assert.equal(shouldClearTelemetry(() => true), true);
  const retained = shouldClearTelemetry(() => false) ? [] : records;
  const cleared = shouldClearTelemetry(() => true) ? [] : records;
  assert.equal(retained.length, 2);
  assert.equal(cleared.length, 0);
});

test('mock browser API provider metrics override the preflight telemetry draft', async () => {
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window');
  const mockWindow = {
    location: { origin: 'http://mocked-lab.test' },
    fetch: async () => {
      throw new Error('Unexpected mock API fallback request.');
    },
  } as unknown as Window;
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: mockWindow,
  });

  try {
    installMockLabApi();
    const request = buildEditRequest({
      engine: 'superdocs',
      documentHtml: '<h1>Mocked context</h1><p>Provider response wins.</p>',
      scope: 'document',
      instruction: 'Clarify',
      requestId: 'mock-api-provider-metrics',
      currentVersionId: 'mock-version',
    });
    const draft = await createTelemetryDraftForRequest({
      request,
      modelLabel: 'core · balanced',
    });
    const response = await mockWindow.fetch('/api/lab/edits', {
      method: 'POST',
      body: JSON.stringify(request),
    });
    const result = (await response.json()) as EditResult;
    const persisted = {
      ...draft,
      ...applyEditResult(
        { ...draft, id: 'mock-telemetry', createdAt: '2026-08-21T00:00:00.000Z' },
        result,
      ),
    };

    assert.notEqual(result.requestMetrics.contextChars, draft.contextChars);
    assert.equal(persisted.contextChars, result.requestMetrics.contextChars);
    assert.equal(persisted.contextChars, request.documentHtml.length + 17);
  } finally {
    if (originalWindow) {
      Object.defineProperty(globalThis, 'window', originalWindow);
    } else {
      delete (globalThis as { window?: Window }).window;
    }
  }
});