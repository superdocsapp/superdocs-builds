import type { ParsedManuscript, TermCandidate, TranslationPacket, TranslationQaReport } from "../types.js";
import { emptySuperDocsState, type SuperDocsRunState } from "../superdocs/integration.js";
import { TermMemory } from "../memory/termMemory.js";
import type { LlmProvider } from "../extract/llmProvider.js";
import { extractTermCandidates, generateStyleNote, type ExtractionWarning } from "../extract/termExtraction.js";
import { confirmTerm, buildDoNotTranslateRules, verifyProtectedTerms } from "../rules/protectedTerms.js";
import { buildTranslationPacket } from "../packet/buildPacket.js";
import { renderPacketArtifacts, renderQaReportMarkdown } from "../packet/artifacts.js";
import { alignManuscripts } from "../align/alignTranslation.js";
import { buildQaReport } from "../qa/chapterReport.js";
import type { Chapter } from "../types.js";

export interface WorkflowRun {
  id: string;
  manuscript: ParsedManuscript;
  targetLanguage: string;
  terms: TermCandidate[];
  extractionWarnings: ExtractionWarning[];
  packet?: TranslationPacket;
  qa?: TranslationQaReport;
  superdocs: SuperDocsRunState;
  metrics: { stages: Record<string, number>; startedAt: string; finishedAt?: string };
}

const runs = new Map<string, WorkflowRun>();
const termMemory = new TermMemory();

function memorySuggestionsFor(manuscript: ParsedManuscript, targetLanguage: string): TermCandidate[] {
  const prior = termMemory.suggestions(manuscript.metadata.title, manuscript.metadata.author, targetLanguage);
  const suggestions: TermCandidate[] = [];
  for (const entry of prior) {
    const lower = entry.canonicalForm.toLocaleLowerCase();
    const chapter = manuscript.chapters.find((candidate) => candidate.blocks.some((block) => block.text.toLocaleLowerCase().includes(lower)));
    if (!chapter) continue;
    const block = chapter.blocks.find((candidate) => candidate.text.toLocaleLowerCase().includes(lower));
    if (!block) continue;
    suggestions.push({
      id: `memory-${entry.canonicalForm.toLocaleLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 32)}`,
      canonicalForm: entry.canonicalForm,
      category: entry.category,
      meaning: entry.meaning,
      pronunciation: { value: entry.pronunciation, confidence: entry.pronunciation ? "medium" : null, note: entry.pronunciation ? "Previously approved pronunciation; confirm against current manuscript context." : "No pronunciation was stored." },
      suggestedPolicy: entry.policy,
      confidence: "high",
      occurrences: [{ chapterId: chapter.id, chapterTitle: chapter.title, blockIndex: chapter.blocks.indexOf(block), evidenceQuote: block.text.slice(0, 120) }],
      status: "suggested",
      evidenceSignals: ["previously approved for the same manuscript/title + author + target language scope"],
      memorySource: "previously_approved",
    });
  }
  return suggestions;
}

export async function prepareRun(manuscript: ParsedManuscript, provider: LlmProvider, targetLanguage: string, approveAll = false): Promise<WorkflowRun> {
  const id = `${manuscript.sourceHash}-${Date.now().toString(36)}`;
  const startedAt = new Date().toISOString();
  const stages: Record<string, number> = {};
  const stageStart = Date.now();
  const { terms: extractedTerms, warnings: extractionWarnings } = await extractTermCandidates(provider, manuscript);
  stages.extraction = Date.now() - stageStart;
  const memoryTerms = memorySuggestionsFor(manuscript, targetLanguage);
  const extractedKeys = new Set(extractedTerms.map((term) => term.canonicalForm.toLocaleLowerCase()));
  const terms = [...extractedTerms, ...memoryTerms.filter((term) => !extractedKeys.has(term.canonicalForm.toLocaleLowerCase()))];
  const termsAfterReview = approveAll ? terms.map(t => confirmTerm(t, "workflow-demo")) : terms;
  const styleStart = Date.now();
  const styleNote = await generateStyleNote(provider, manuscript);
  stages.style = Date.now() - styleStart;
  const packetStart = Date.now();
  const rules = buildDoNotTranslateRules(termsAfterReview);
  const packet = buildTranslationPacket({ manuscript, allTerms: termsAfterReview, confirmedRules: rules, styleNote, targetLanguage });
  stages.packet = Date.now() - packetStart;
  const run: WorkflowRun = { id, manuscript, targetLanguage, terms: termsAfterReview, extractionWarnings, packet, superdocs: emptySuperDocsState(), metrics: { stages, startedAt } };
  termMemory.remember(manuscript.metadata.title, manuscript.metadata.author, targetLanguage, termsAfterReview);
  run.metrics.finishedAt = new Date().toISOString();
  runs.set(id, run);
  return run;
}

export function getRun(id: string): WorkflowRun | undefined { return runs.get(id); }

export function reviewTerms(id: string, decisions: Array<{ termId: string; action: "approve" | "reject" }>): WorkflowRun {
  const run = runs.get(id); if (!run) throw new Error("Run not found");
  run.terms = run.terms.map(t => {
    const d = decisions.find(x => x.termId === t.id); if (!d) return t;
    return d.action === "approve" ? confirmTerm(t, "human-review") : { ...t, status: "rejected" as const, reviewedBy: "human-review", reviewedAt: new Date().toISOString() };
  });
  const rules = buildDoNotTranslateRules(run.terms);
  const styleNote = run.packet!.styleNote;
  run.packet = buildTranslationPacket({ manuscript: run.manuscript, allTerms: run.terms, confirmedRules: rules, styleNote, targetLanguage: run.targetLanguage });
  termMemory.remember(run.manuscript.metadata.title, run.manuscript.metadata.author, run.targetLanguage, run.terms);
  return run;
}

export function validateReturnedTranslation(id: string, translatedChapters: Chapter[]): TranslationQaReport {
  const run = runs.get(id); if (!run || !run.packet) throw new Error("Run not found or packet not ready");
  const qaStart = Date.now();
  const rules = run.packet.doNotTranslateRules;
  const alignments = alignManuscripts(run.manuscript.chapters, translatedChapters);
  const findings = verifyProtectedTerms({ sourceChapters: run.manuscript.chapters, translatedChapters, chapterAlignments: alignments, rules, allTerms: run.terms });
  run.qa = buildQaReport(run.manuscript.chapters, rules, findings);
  run.qa = { ...run.qa, findings: run.qa.findings.map(f => ({ ...f, reviewStatus: "open" as const })) };
  run.metrics.stages.qa = Date.now() - qaStart;
  run.metrics.finishedAt = new Date().toISOString();
  return run.qa;
}

export function exportArtifacts(id: string) {
  const run = runs.get(id); if (!run || !run.packet) throw new Error("Run not found or packet not ready");
  const artifacts = renderPacketArtifacts(run.packet);
  if (run.qa) artifacts.qaReportMarkdown = renderQaReportMarkdown(run.qa);
  return { run, artifacts };
}

export function updateSuperDocsState(id: string, state: SuperDocsRunState): WorkflowRun {
  const run = runs.get(id); if (!run) throw new Error("Run not found");
  run.superdocs = state;
  return run;
}

export function resetRuns() { runs.clear(); }

export function setFindingReviewStatus(id: string, findingId: string, status: "approved" | "rejected" | "intentional" | "manual_review"): TranslationQaReport {
  const run = runs.get(id); if (!run?.qa) throw new Error("QA report not found");
  run.qa = { ...run.qa, findings: run.qa.findings.map(f => f.id === findingId ? { ...f, reviewStatus: status } : f) };
  return run.qa;
}
