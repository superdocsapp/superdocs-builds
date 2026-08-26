import type { EditInput, EditResult, LabConfig } from '@workspace/api-client-react';

type MockLabWindow = Window & {
  __aiEditingLabMockRequests?: EditInput[];
};

const config: LabConfig = {
  appMode: 'compare',
  engines: [
    {
      id: 'diy',
      label: 'DIY Toolkit',
      configured: true,
      modelLabel: 'gpt-4o-mini',
      capabilities: ['selection editing', 'whole-document editing', 'structured JSON'],
    },
    {
      id: 'superdocs',
      label: 'SuperDocs Hosted',
      configured: true,
      modelLabel: 'core · balanced',
      modelTier: 'core',
      thinkingDepth: 'balanced',
      capabilities: ['asynchronous review jobs', 'chunk-level HTML proposals'],
    },
  ],
};

function json(data: unknown): Response {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

const MOCK_REVISION_SUFFIX =
  ' <em>— tightened by the mock engine for a clearer read.</em>';

/**
 * Produce a VISIBLE, deterministic revision of an HTML block so browser tests
 * can verify that accepting a proposal actually changes the document.
 */
function reviseBlock(block: string): string {
  const revised = block.replace(
    /<\/(p|li|blockquote|h[1-6])>\s*$/i,
    (_match, tag: string) => `${MOCK_REVISION_SUFFIX}</${tag}>`,
  );
  return revised === block ? `<p>${block}${MOCK_REVISION_SUFFIX}</p>` : revised;
}

function mockEdit(input: EditInput): EditResult {
  const selectedPayloadChars = (
    input.selectionHtml ??
    input.selectionText ??
    ''
  ).length;
  const providerContextChars =
    input.engine === 'superdocs' || input.scope === 'document'
      ? input.documentHtml.length
      : selectedPayloadChars;

  const targetBlock =
    input.scope === 'selection'
      ? input.selectionHtml ?? null
      : input.documentHtml.match(/<p\b[^>]*>[\s\S]*?<\/p>/i)?.[0] ?? null;
  const revisedBlock = targetBlock ? reviseBlock(targetBlock) : null;
  const candidateDocumentHtml =
    targetBlock && revisedBlock && input.documentHtml.includes(targetBlock)
      ? input.documentHtml.replace(targetBlock, () => revisedBlock)
      : input.scope === 'selection'
        ? // Let the app apply the change through its selection-range machinery.
          null
        : input.documentHtml;

  return {
    engine: input.engine,
    engineLabel: input.engine === 'diy' ? 'DIY Toolkit' : 'SuperDocs Hosted',
    promptVersion:
      input.engine === 'diy'
        ? 'diy-selection-context-v2'
        : 'superdocs-hosted-v1',
    requestId: input.requestId,
    success: true,
    proposedChanges:
      targetBlock && revisedBlock
        ? [
            {
              id: `mock-change-${input.requestId}`,
              operation: 'edit',
              oldHtml: targetBlock,
              newHtml: revisedBlock,
              explanation:
                'Deterministic mock revision used for repeatable UI tests.',
              target: null,
              chunkId: null,
              status: 'pending',
            },
          ]
        : [],
    candidateDocumentHtml,
    assistantMessage: 'Development mock proposal',
    latencyMs: 10,
    reviewWaitMs: null,
    usage:
      input.engine === 'diy'
        ? { inputTokens: 10, outputTokens: 5, totalTokens: 15, hostedUsage: null }
        : {
            inputTokens: null,
            outputTokens: null,
            totalTokens: null,
            hostedUsage: '{"credits":1}',
          },
    retryCount: 0,
    requestMetrics: {
      // Keep the mock independent from client estimation. The fixed offset lets
      // browser tests prove completed telemetry uses server measurements.
      promptChars:
        input.engine === 'diy'
          ? input.instruction.length + providerContextChars + 47
          : null,
      contextChars: providerContextChars + 17,
    },
    error: null,
    review: null,
    startedAt: new Date().toISOString(),
    completedAt: new Date().toISOString(),
  };
}

/**
 * Development-only browser harness for repeatable UI tests. It is activated
 * solely by ?mock-api=1 and never included in production builds.
 */
export function installMockLabApi(): void {
  const originalFetch = window.fetch.bind(window);
  const mockWindow = window as MockLabWindow;
  mockWindow.__aiEditingLabMockRequests = [];

  window.fetch = async (input, init) => {
    const url = new URL(
      input instanceof Request ? input.url : input.toString(),
      window.location.origin,
    );
    if (url.pathname === '/api/healthz') return json({ status: 'ok' });
    if (url.pathname === '/api/lab/config') return json(config);
    if (url.pathname === '/api/lab/edits') {
      const body = JSON.parse(String(init?.body ?? '{}')) as EditInput;
      mockWindow.__aiEditingLabMockRequests?.push(body);
      return json(mockEdit(body));
    }
    if (url.pathname === '/api/lab/reviews/cancel') {
      return json({ cancelled: true });
    }
    return originalFetch(input, init);
  };
}