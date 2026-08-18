import type { Intake, StrengthBand } from "./types";

const STRENGTH_CALIBRATION: Record<StrengthBand, string> = {
  strong:
    "Strength band: STRONG. Confident, specific, evidence-led language is appropriate. " +
    "Still do not exceed what the evidence supports — no vague superlatives without a concrete claim backing them.",
  solid:
    "Strength band: SOLID. Positive but measured. Competent-and-reliable framing, not exceptional-and-outstanding. " +
    "Avoid words like 'best', 'exceptional', 'outstanding', 'brilliant'. Prefer 'consistently', 'dependable', 'met expectations'.",
  mixed:
    "Strength band: MIXED. The letter must read as genuinely mixed, not softened into positive. " +
    "State strengths and weaknesses side by side, in proportion to what was reported. Do not resolve the mix into an overall positive tone.",
  reluctant:
    "Strength band: RELUCTANT/LUKEWARM. This must read as a lukewarm reference, not a warm one dressed down. " +
    "Forbid superlatives and enthusiasm markers entirely (no 'pleasure to recommend', no exclamation of confidence). " +
    "Use flat, factual, hedged phrasing. State the reservations directly rather than burying or softening them. " +
    "The letter should leave a reader with a measured, cautious impression consistent with the writer's actual reservations.",
};

const PURPOSE_LABEL: Record<Intake["purpose"], string> = {
  graduate_school: "graduate school admission",
  job: "a job application",
  fellowship_or_award: "a fellowship or award application",
  other: "an unspecified application",
};

export function buildDraftInstruction(intake: Intake): string {
  const purposeLabel =
    intake.purpose === "other" && intake.purposeOther
      ? intake.purposeOther
      : PURPOSE_LABEL[intake.purpose];

  const evidenceLines = intake.evidence
    .filter((item) => item.claim.trim() || item.evidence.trim())
    .map((item, i) => `${i + 1}. Claim: "${item.claim}" — Evidence: "${item.evidence}"`)
    .join("\n");

  const lengthLabel =
    intake.lengthPreference === "brief"
      ? "Keep it brief: roughly 200-300 words."
      : intake.lengthPreference === "detailed"
        ? "Write a detailed letter: roughly 500-700 words."
        : "Standard length: roughly 300-450 words.";

  return `Replace the placeholder in this document with a letter of recommendation.

WRITER: ${intake.writerName}, ${intake.writerRole}.
SUBJECT: ${intake.subjectName}, ${intake.subjectRole}.
RELATIONSHIP: ${intake.relationship}, known for ${intake.relationshipDurationMonths} months.
PURPOSE: This letter supports ${purposeLabel}.

${STRENGTH_CALIBRATION[intake.strengthBand]}

CLAIMS AND EVIDENCE (use only these — do not invent accomplishments, numbers, or anecdotes beyond what is listed):
${evidenceLines || "(No specific evidence was provided — keep claims generic and avoid fabricating specifics.)"}

RESERVATIONS STATED BY THE WRITER (must be reflected in the letter, not omitted or softened away):
${intake.reservations.trim() || "(None stated.)"}

${intake.toneNotes ? `ADDITIONAL TONE NOTES FROM THE WRITER: ${intake.toneNotes}` : ""}

${lengthLabel}

Write in the first person as ${intake.writerName}. Sign off with the writer's name. Do not add any accomplishment, metric, or claim that is not traceable to the evidence list above.`.trim();
}
