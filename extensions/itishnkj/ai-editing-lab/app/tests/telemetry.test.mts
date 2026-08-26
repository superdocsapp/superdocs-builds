import assert from 'node:assert/strict';
import test from 'node:test';
import {
  createTelemetryDraft,
  applyEditResult,
  estimateContext,
  estimateRequestContext,
  estimateDiyCost,
  makeRequestFingerprint,
  DIY_PROMPT_VERSION,
} from '../src/lib/telemetry.ts';

test('calculates a labeled estimate from actual DIY provider tokens', () => {
  const record = {
    engine: 'diy' as const,
    modelLabel: 'gpt-4o-mini',
    usage: { inputTokens: 1_000_000, outputTokens: 1_000_000, totalTokens: 2_000_000, hostedUsage: null },
  };
  const estimate = estimateDiyCost(record);
  assert.equal(estimate.state, 'estimated');
  assert.equal(estimate.usd, 0.75);
});

test('never treats unknown DIY model pricing as zero', () => {
  const estimate = estimateDiyCost({
    engine: 'diy',
    modelLabel: 'private-model',
    usage: { inputTokens: 10, outputTokens: 10, totalTokens: 20, hostedUsage: null },
  });
  assert.equal(estimate.state, 'not_configured');
  assert.equal(estimate.usd, null);
  assert.equal(estimate.label, 'Pricing not configured');
});

test('applies completed hosted usage and server-measured request metrics', async () => {
  const draft = await createTelemetryDraft({
    requestId: 'hosted-request',
    engine: 'superdocs',
    modelLabel: 'core · balanced',
    documentHtml: '<p>Original hosted document.</p>',
    scope: 'document',
    instruction: 'Clarify this document',
  });
  const patch = applyEditResult(
    { ...draft, id: 'telemetry-1', createdAt: new Date().toISOString() },
    {
      success: true,
      error: null,
      latencyMs: 400,
      retryCount: 0,
      promptVersion: 'superdocs-hosted-v1',
      usage: {
        inputTokens: null,
        outputTokens: null,
        totalTokens: null,
        hostedUsage: '{"credits":1}',
      },
      requestMetrics: { promptChars: null, contextChars: 321 },
    } as Parameters<typeof applyEditResult>[1],
  );
  assert.equal(patch.hostedUsageState, 'actual');
  assert.equal(patch.usage?.hostedUsage, '{"credits":1}');
  assert.equal(patch.contextChars, 321);
  assert.equal(patch.promptVersion, 'superdocs-hosted-v1');
});

test('records imported document metadata without document contents', async () => {
  const draft = await createTelemetryDraft({
    requestId: 'imported-request',
    engine: 'diy',
    modelLabel: 'gpt-4o-mini',
    documentHtml: '<p>Confidential document contents never enter telemetry metadata.</p>',
    scope: 'document',
    instruction: 'Clarify the introduction',
    documentMetadata: {
      documentId: 'document-session-1',
      documentSource: 'imported',
      fileType: 'docx',
      documentWordCount: 7,
      documentCharacterCount: 49,
    },
  });
  assert.equal(draft.documentId, 'document-session-1');
  assert.equal(draft.documentSource, 'imported');
  assert.equal(draft.fileType, 'docx');
  assert.equal(draft.documentWordCount, 7);
  assert.equal(draft.documentCharacterCount, 49);
  assert.equal('originalFileName' in draft, false);
});

test('uses bounded selection context while retaining whole documents for document edits', () => {
  const documentHtml = `<h1>Report</h1>${'<p>Nearby document structure.</p>'.repeat(300)}`;
  const selection = 'Nearby document structure.';
  const selectionEstimate = estimateContext({
    documentHtml,
    selectionText: selection,
    scope: 'selection',
    instruction: 'Make concise',
  });
  const documentEstimate = estimateContext({
    documentHtml,
    scope: 'document',
    instruction: 'Make concise',
  });
  assert.equal(selectionEstimate.strategy, 'selection-with-nearby-structure');
  assert.ok(selectionEstimate.contextChars < documentHtml.length);
  assert.equal(documentEstimate.strategy, 'full-document');
  assert.equal(documentEstimate.contextChars, documentHtml.length);
});

test('counts the HTML selection payload and contextual labels sent to DIY', () => {
  const selectionHtml = '<p data-mark="tracked"><strong>Important note.</strong></p>';
  const documentHtml = `<p>${'Filler context. '.repeat(120)}</p>${selectionHtml}<p>After.</p>`;
  const estimate = estimateContext({
    documentHtml,
    selectionHtml,
    selectionText: 'Important note.',
    scope: 'selection',
    instruction: 'Clarify this note',
  });
  const expected =
    'SELECTED CONTENT:\n'.length +
    selectionHtml.length +
    '\n\nDOCUMENT OUTLINE:\n(no headings)\n\nNEARBY STRUCTURE (reference only; do not rewrite it):\n'.length +
    estimate.nearbyStructureChars;
  assert.equal(estimate.contextChars, expected);
  assert.ok(estimate.contextChars > selectionHtml.length);
});

test('uses the server selection threshold for near-full and oversized selections', () => {
  const nearFull = estimateContext({
    documentHtml: '<p>Short document with a selected sentence.</p>',
    selectionText: 'Short document with a selected sentence.',
    scope: 'selection',
    instruction: 'Clarify',
  });
  const oversized = estimateContext({
    documentHtml: `<p>${'x'.repeat(12_001)}</p>`,
    selectionText: 'x'.repeat(12_001),
    scope: 'selection',
    instruction: 'Clarify',
  });
  assert.equal(nearFull.strategy, 'selection-with-nearby-structure');
  assert.equal(oversized.strategy, 'full-document-for-reliability');
});

test('derives DIY prompt characters from the complete initial message layout', () => {
  const documentHtml = '<p>Original.</p>';
  const instruction = 'Make it clearer';
  const estimate = estimateRequestContext({
    engine: 'diy',
    documentHtml,
    scope: 'document',
    instruction,
  });
  const system =
    'You edit an existing professional rich-text document.\n' +
    "Obey the user's instruction exactly.\n" +
    'Preserve meaning unless the instruction says otherwise.\n' +
    'Preserve unrelated content and relevant HTML formatting.\n' +
    'Modify only the requested scope.\n' +
    'Return valid JSON and no markdown fences or commentary.\n' +
    'The JSON shape is: {"replacement_html":"<valid HTML>","explanation":"brief reason"}.\n' +
    'Never include scripts, iframes, event-handler attributes, or external embeds.';
  const user = [
    'Prompt version: diy-selection-context-v2',
    'Scope: document',
    `Instruction: ${instruction}`,
    '',
    'CONTENT TO EDIT:',
    documentHtml,
    '',
    'Return the complete edited document HTML.',
  ].join('\n');
  assert.equal(estimate.estimatedPromptChars, system.length + user.length);
});

test('reports hosted selection requests as full document context', () => {
  const documentHtml = `<h1>Confidential report</h1>${'<p>Full provider payload.</p>'.repeat(120)}`;
  const selectionText = 'Full provider payload.';
  const hosted = estimateRequestContext({
    engine: 'superdocs',
    documentHtml,
    selectionText,
    scope: 'selection',
    instruction: 'Improve only the selected paragraph',
  });
  assert.equal(hosted.strategy, 'full-document');
  assert.equal(hosted.contextChars, documentHtml.length);
});

test('uses private fingerprints by engine and persists no request content in telemetry', async () => {
  const documentHtml = '<p>Private source content that must not be stored as telemetry.</p>';
  const diyHash = await makeRequestFingerprint({
    engine: 'diy',
    documentHtml,
    scope: 'document',
    instruction: 'Improve clarity',
  });
  const hostedHash = await makeRequestFingerprint({
    engine: 'superdocs',
    documentHtml,
    scope: 'document',
    instruction: 'Improve clarity',
  });
  assert.notEqual(diyHash, hostedHash);

  const draft = await createTelemetryDraft({
    requestId: 'request-1',
    engine: 'diy',
    modelLabel: 'gpt-4o-mini',
    documentHtml,
    scope: 'document',
    instruction: 'Improve clarity',
  });
  const serialized = JSON.stringify(draft);
  assert.equal(serialized.includes(documentHtml), false);
  assert.equal(serialized.includes('Improve clarity'), false);
  assert.equal(draft.promptVersion, DIY_PROMPT_VERSION);
  assert.equal(DIY_PROMPT_VERSION, 'diy-selection-context-v2');
});