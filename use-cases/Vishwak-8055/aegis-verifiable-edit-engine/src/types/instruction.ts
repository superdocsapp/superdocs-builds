export type ScopeSpec =
  | { kind: 'whole-document' }
  | { kind: 'style-only' }
  | { kind: 'paragraph-index'; index: number }
  | { kind: 'heading'; headingText: string }
  | { kind: 'unscoped' };

export type EditKind = 'style-only' | 'targeted-fix' | 'value-change' | 'restructure' | 'unspecified';

export interface RequestedValueChange {
  /** Raw substring from the instruction that expressed the requested change, kept for evidence. */
  raw: string;
  /** The new value the instruction explicitly asked for, if it named one. */
  toValueRaw?: string;
}

export interface CompiledIntent {
  instructionText: string;
  summary: string;
  editKind: EditKind;
  scope: ScopeSpec;
  requestedValueChanges: RequestedValueChange[];
  /** False only when the instruction explicitly says meaning/values may change. */
  protectSemantics: boolean;
  protectValues: boolean;
  /** Heuristic confidence in this extraction, 0..1. Low confidence does not relax protection — it only affects scope strictness (see scopeVerifier). */
  confidence: number;
  /** Set when compileIntent had to fall back to an AI provider for genuinely ambiguous phrasing (see src/intent/aiProvider.ts). Empty in this repo's default configuration. */
  aiAssisted: boolean;
}
