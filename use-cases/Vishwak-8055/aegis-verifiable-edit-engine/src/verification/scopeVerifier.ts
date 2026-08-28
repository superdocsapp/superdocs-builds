import type { VerificationContext } from '../types/context.js';
import type { CheckerOutcome, Finding } from '../types/verification.js';
import { nthOfKind } from '../types/document.js';

interface ScopeResolution {
  /** 'all' means no restriction (whole-document / style-only / unscoped intents don't constrain WHICH blocks may change). */
  ids: 'all' | Set<string>;
  targetNotFound: boolean;
}

export function runScopeVerifier(ctx: VerificationContext): CheckerOutcome {
  const start = performance.now();
  const findings: Finding[] = [];
  let counter = 0;
  const nextId = () => `scope:${++counter}`;

  const resolution = resolveInScope(ctx);

  if (resolution.targetNotFound) {
    findings.push({
      id: nextId(),
      checker: 'scope',
      kind: 'SCOPE_TARGET_NOT_FOUND',
      confidence: 0.9,
      message: 'The instruction named a specific paragraph/section that does not exist in the document. Every change is being treated as out of scope until this is resolved.',
    });
  }

  if (resolution.ids !== 'all') {
    for (const entry of ctx.alignment) {
      if (entry.kind === 'unchanged') continue;

      if (entry.kind === 'inserted') {
        findings.push({
          id: nextId(),
          checker: 'scope',
          kind: 'UNINTENDED_SCOPE_CHANGE',
          confidence: 0.85,
          message: 'New content was inserted outside the requested scope.',
          location: { afterBlockId: entry.afterId },
        });
        continue;
      }

      const beforeId = entry.beforeId;
      if (!resolution.ids.has(beforeId)) {
        findings.push({
          id: nextId(),
          checker: 'scope',
          kind: 'UNINTENDED_SCOPE_CHANGE',
          confidence: 0.9,
          message: `Content outside the requested scope was ${entry.kind === 'deleted' ? 'deleted' : 'modified'}.`,
          location: { beforeBlockId: beforeId, afterBlockId: 'afterId' in entry ? entry.afterId : undefined },
        });
      }
    }
  }

  return { checker: 'scope', findings, durationMs: performance.now() - start };
}

function resolveInScope(ctx: VerificationContext): ScopeResolution {
  const scope = ctx.intent.scope;

  if (scope.kind === 'whole-document' || scope.kind === 'style-only' || scope.kind === 'unscoped') {
    return { ids: 'all', targetNotFound: false };
  }

  if (scope.kind === 'paragraph-index') {
    const block = nthOfKind(ctx.before, 'paragraph', scope.index);
    if (!block) return { ids: new Set(), targetNotFound: true };
    return { ids: new Set([block.id]), targetNotFound: false };
  }

  // scope.kind === 'heading'
  const headingIndex = ctx.before.blocks.findIndex(
    (b) => b.type === 'heading' && b.text.toLowerCase().includes(scope.headingText.toLowerCase()),
  );
  if (headingIndex === -1) return { ids: new Set(), targetNotFound: true };

  const headingBlock = ctx.before.blocks[headingIndex];
  const level = headingBlock.type === 'heading' ? headingBlock.level : 1;
  const ids = new Set<string>([headingBlock.id]);
  for (let i = headingIndex + 1; i < ctx.before.blocks.length; i++) {
    const block = ctx.before.blocks[i];
    if (block.type === 'heading' && block.level <= level) break;
    ids.add(block.id);
  }
  return { ids, targetNotFound: false };
}
