import type { VerificationContext } from '../types/context.js';
import type { CheckerOutcome, Finding } from '../types/verification.js';
import type { CompiledIntent } from '../types/instruction.js';
import { findBlock, type BlockAlignment } from './normalize.js';
import { blockPlainText } from '../types/document.js';
import { extractProtectedValues, type ExtractedValue, type ProtectedValueKind } from './protectedValues.js';

export function runProtectedValueVerifier(ctx: VerificationContext): CheckerOutcome {
  const start = performance.now();
  const findings: Finding[] = [];
  let counter = 0;
  const nextId = () => `protected_value:${++counter}`;

  for (const entry of ctx.alignment) {
    if (entry.kind === 'modified') {
      findings.push(...compareModifiedBlock(ctx, entry, nextId));
    } else if (entry.kind === 'deleted') {
      findings.push(...reportLostValues(ctx, entry, nextId));
    }
  }

  return { checker: 'protected_value', findings, durationMs: performance.now() - start };
}

function compareModifiedBlock(
  ctx: VerificationContext,
  entry: Extract<BlockAlignment, { kind: 'modified' }>,
  nextId: () => string,
): Finding[] {
  const findings: Finding[] = [];
  const beforeBlock = findBlock(ctx.before, entry.beforeId);
  const afterBlock = findBlock(ctx.after, entry.afterId);
  if (!beforeBlock || !afterBlock) return findings;

  const beforeValues = extractProtectedValues(blockPlainText(beforeBlock));
  const afterValues = extractProtectedValues(blockPlainText(afterBlock));

  const kinds = new Set<ProtectedValueKind>([...beforeValues.map((v) => v.kind), ...afterValues.map((v) => v.kind)]);

  for (const kind of kinds) {
    const beforeList = beforeValues.filter((v) => v.kind === kind);
    const afterList = afterValues.filter((v) => v.kind === kind);
    const length = Math.max(beforeList.length, afterList.length);

    for (let i = 0; i < length; i++) {
      const b = beforeList[i];
      const a = afterList[i];
      const location = { beforeBlockId: entry.beforeId, afterBlockId: entry.afterId };

      if (b && a) {
        if (b.normalized === a.normalized) continue;
        const requested = isRequestedTransition(ctx.intent, kind, a.normalized);
        if (!ctx.intent.protectValues) {
          findings.push(
            makeFinding(nextId(), 'PROTECTED_VALUE_CHANGE_UNENFORCED', b, a, kind, location,
              `${kind} changed from "${b.raw}" to "${a.raw}"; not flagged because this edit explicitly released value protection.`),
          );
          continue;
        }
        if (requested) {
          findings.push(
            makeFinding(nextId(), 'PROTECTED_VALUE_REQUESTED_CHANGE', b, a, kind, location,
              `${kind} changed from "${b.raw}" to "${a.raw}", matching a change explicitly requested in the instruction.`),
          );
          continue;
        }
        findings.push(
          makeFinding(nextId(), `PROTECTED_VALUE_${kind.toUpperCase()}_CHANGED`, b, a, kind, location,
            `${kind} changed from "${b.raw}" to "${a.raw}" without being requested.`),
        );
      } else if (b && !a) {
        findings.push(
          makeFinding(nextId(), 'PROTECTED_VALUE_REMOVED', b, undefined, kind, location,
            `${kind} "${b.raw}" was present before the edit and is no longer present.`),
        );
      } else if (!b && a) {
        findings.push(
          makeFinding(nextId(), 'PROTECTED_VALUE_INSERTED', undefined, a, kind, location,
            `A new ${kind} value "${a.raw}" appeared that was not present before the edit.`),
        );
      }
    }
  }

  return findings;
}

function reportLostValues(
  ctx: VerificationContext,
  entry: Extract<BlockAlignment, { kind: 'deleted' }>,
  nextId: () => string,
): Finding[] {
  const beforeBlock = findBlock(ctx.before, entry.beforeId);
  if (!beforeBlock) return [];
  const values = extractProtectedValues(blockPlainText(beforeBlock));
  return values.map((v) =>
    makeFinding(
      nextId(),
      'PROTECTED_VALUE_LOST_WITH_BLOCK',
      v,
      undefined,
      v.kind,
      { beforeBlockId: entry.beforeId },
      `${v.kind} "${v.raw}" was removed because its entire containing block was deleted.`,
    ),
  );
}

function makeFinding(
  id: string,
  kind: string,
  before: ExtractedValue | undefined,
  after: ExtractedValue | undefined,
  _valueKind: ProtectedValueKind,
  location: { beforeBlockId?: string; afterBlockId?: string },
  message: string,
): Finding {
  return {
    id,
    checker: 'protected_value',
    kind,
    confidence: 0.95,
    message,
    before: before?.raw,
    after: after?.raw,
    location,
  };
}

function isRequestedTransition(intent: CompiledIntent, kind: ProtectedValueKind, afterNormalized: string): boolean {
  return intent.requestedValueChanges.some((rvc) => {
    if (!rvc.toValueRaw) return false;
    return extractProtectedValues(rvc.toValueRaw).some((v) => v.kind === kind && v.normalized === afterNormalized);
  });
}
