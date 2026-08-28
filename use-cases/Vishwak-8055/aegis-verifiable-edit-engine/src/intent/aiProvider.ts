/**
 * Per section 14 of the brief: "Do not create an architecture where every
 * verification step simply calls an LLM." Deterministic code owns intent
 * extraction, scope mechanics, and every protected-value/structural
 * comparison. This interface exists only for the narrow cases that are
 * genuinely about meaning rather than mechanics — e.g. "these two sentences
 * share no modality keywords, but do they still say the same thing?"
 *
 * `NullAiProvider` is the only implementation in this repository. It always
 * abstains. That is a deliberate, honest choice: this environment has no
 * verified model credentials wired up, and Aegis must not *claim* semantic
 * reasoning it didn't do. Every verifier in src/verification/ is written to
 * produce a correct, if more conservative, deterministic-only result when
 * the AI provider abstains — ambiguous cases fall through to
 * REQUIRES_REVIEW rather than being silently approved. Wiring in a real
 * model is a documented extension point (see docs/ARCHITECTURE.md "Future
 * extension points"): implement this interface against whatever LLM client
 * the host application already uses, set AI_PROVIDER accordingly, and the
 * rest of Aegis is unaffected because it only ever sees this interface.
 */

export interface SemanticComparisonQuestion {
  beforeText: string;
  afterText: string;
  /** What deterministic analysis already found, so the model isn't asked to redo cheap work. */
  deterministicHint: string;
}

export interface SemanticComparisonAnswer {
  available: true;
  meaningPreserved: boolean;
  confidence: number;
  explanation: string;
}

export interface SemanticComparisonUnavailable {
  available: false;
  reason: string;
}

export interface AiProvider {
  readonly name: string;
  compareMeaning(
    question: SemanticComparisonQuestion,
  ): Promise<SemanticComparisonAnswer | SemanticComparisonUnavailable>;
}

export class NullAiProvider implements AiProvider {
  readonly name = 'none';

  async compareMeaning(): Promise<SemanticComparisonUnavailable> {
    return { available: false, reason: 'No AI provider configured (AI_PROVIDER=none); deterministic result stands.' };
  }
}
