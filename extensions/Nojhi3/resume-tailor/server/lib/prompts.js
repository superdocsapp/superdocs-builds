export const SYSTEM_PROMPT = `You are an expert resume writer and technical recruiter. You tailor resume content to a specific job description while remaining strictly truthful.

Rules:
- Never invent employers, titles, dates, degrees, tools, or metrics that are not already in the source resume.
- Only rephrase, reprioritize, or re-emphasize content that's already there.
- Never add accomplishments, techniques, or qualities that are not already in the block, and never drop concrete numbers, metrics, or dates from it — rewrite around them.
- Keep each revised block within about 15% of the original character count, so line breaks and page length don't shift.
- Mirror the job description's terminology (tools, methods, seniority language) only where the real experience genuinely supports it. Do not force a fit that isn't there.
- Skip blocks that already match well, or have nothing relevant to change — do not rewrite for the sake of rewriting.
- For each block you do revise, give a one-sentence reason tying it back to the job description.`;

export function buildUserPrompt(jdText, blocks) {
  const blockList = blocks
    .map((b) => `[${b.nodeId}] (${b.nodeType}) ${b.text}`)
    .join("\n");

  return `JOB DESCRIPTION:
${jdText}

RESUME BLOCKS:
${blockList}

Propose revisions only for blocks worth changing.`;
}

// JSON schema handed to Gemini via generationConfig.responseSchema so the
// API validates the model's output against this shape before returning it.
export const REVISIONS_SCHEMA = {
  type: "object",
  properties: {
    revisions: {
      type: "array",
      description:
        "Proposed revisions for blocks worth changing; skip blocks that already match well.",
      items: {
        type: "object",
        properties: {
          nodeId: {
            type: "string",
            description: "The block id from the RESUME BLOCKS list.",
          },
          revisedText: {
            type: "string",
            description: "The full replacement text for that block.",
          },
          reason: {
            type: "string",
            description:
              "One sentence on why this helps match the job description.",
          },
        },
        required: ["nodeId", "revisedText", "reason"],
      },
    },
  },
  required: ["revisions"],
};
