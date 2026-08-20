import { GoogleGenerativeAI } from "@google/generative-ai";
import { SYSTEM_PROMPT, buildUserPrompt, REVISIONS_SCHEMA } from "./prompts.js";

// Swap the model here for any other Gemini model. Gemini's JSON mode
// (responseMimeType + responseSchema) validates the response against the
// schema before returning it, which is the equivalent of Anthropic's
// tool-forced JSON.
const MODEL = "gemini-2.5-flash";

const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);

export async function getResumeRevisions(jdText, blocks) {
  const model = genAI.getGenerativeModel({
    model: MODEL,
    systemInstruction: SYSTEM_PROMPT,
    generationConfig: {
      responseMimeType: "application/json",
      responseSchema: REVISIONS_SCHEMA,
    },
  });

  const result = await model.generateContent(buildUserPrompt(jdText, blocks));
  const text = result.response.text();

  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (err) {
    throw new Error(`Model returned invalid JSON: ${text.slice(0, 200)}`);
  }

  // With a response schema Gemini returns the full object; be lenient in
  // case it returns the bare revisions array instead.
  const revisions = Array.isArray(parsed) ? parsed : parsed?.revisions;
  if (!Array.isArray(revisions)) {
    throw new Error("Model response is missing the revisions array.");
  }
  return revisions;
}
