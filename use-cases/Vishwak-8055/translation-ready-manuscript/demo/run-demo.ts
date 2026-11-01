/**
 * End-to-end demo of the Translation-Ready Manuscript use case.
 *
 * Runs with zero configuration: `npm run demo`. Uses MockLlmProvider (a
 * fixed, realistic set of term suggestions grounded in real quotes from the
 * fixture) unless ANTHROPIC_API_KEY is set in the environment, in which
 * case it uses the real Anthropic provider instead -- same pipeline code
 * either way, per the provider abstraction in src/extract/llmProvider.ts.
 *
 * The SuperDocs section only runs live calls if SUPERDOCS_API_KEY is set;
 * otherwise it prints what it would do and why it's skipping, rather than
 * silently pretending to succeed.
 */
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { parseManuscript } from "../src/ingest/parseManuscript.js";
import { AnthropicProvider, MockLlmProvider, type RawTermSuggestion } from "../src/extract/llmProvider.js";
import { extractTermCandidates, generateStyleNote } from "../src/extract/termExtraction.js";
import { buildDoNotTranslateRules, confirmTerm, verifyProtectedTerms } from "../src/rules/protectedTerms.js";
import { alignManuscripts } from "../src/align/alignTranslation.js";
import { buildQaReport, renderQaReportAsText } from "../src/qa/chapterReport.js";
import { buildTranslationPacket } from "../src/packet/buildPacket.js";
import { checkIntegrity, diffDocumentBodies, diffMetadata } from "../src/diff/documentDiff.js";
import { loadLocalEnv } from "../src/config/env.js";
import { SuperDocsIntegration, emptySuperDocsState } from "../src/superdocs/integration.js";
import type { Chapter, TermCandidate } from "../src/types.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(__dirname, "..");
const outDir = path.join(root, "demo-output");
loadLocalEnv(root);

function section(title: string) {
  console.log("\n" + "=".repeat(78));
  console.log(title);
  console.log("=".repeat(78));
}

// Realistic mock term suggestions -- every evidenceQuote below is a real,
// exact substring of tests/fixtures/alice.txt, so this exercises the same
// evidence-verification path a real provider response would go through.
const MOCK_TERMS: RawTermSuggestion[] = [
  {
    canonicalForm: "Dinah",
    category: "character",
    meaning: "Alice's pet cat, mentioned throughout but never physically present in these chapters.",
    pronunciation: "DY-nuh",
    pronunciationConfidence: "medium",
    suggestedPolicy: "do_not_translate",
    confidence: "high",
    occurrences: [{ chapterId: "ch01-down-the-rabbit-hole", evidenceQuote: "Dinah was the cat" }],
  },
  {
    canonicalForm: "White Rabbit",
    category: "character",
    meaning: "The waistcoat-wearing rabbit whose hurry sets the whole story in motion.",
    pronunciation: null,
    pronunciationConfidence: null,
    suggestedPolicy: "preserve_consistently",
    confidence: "high",
    occurrences: [{ chapterId: "ch01-down-the-rabbit-hole", evidenceQuote: "a White Rabbit with pink eyes ran" }],
  },
  {
    canonicalForm: "Cheshire cat",
    category: "character",
    meaning: "The perpetually grinning cat Alice meets at the Duchess's house.",
    pronunciation: "CHESH-er",
    pronunciationConfidence: "medium",
    suggestedPolicy: "preserve_consistently",
    confidence: "high",
    occurrences: [{ chapterId: "ch06-pig-and-pepper", evidenceQuote: "It’s a Cheshire cat" }],
  },
  {
    canonicalForm: "Mock Turtle",
    category: "character",
    meaning: "A melancholy creature named for mock turtle soup -- the name itself is a pun that may not survive translation intact.",
    pronunciation: null,
    pronunciationConfidence: null,
    suggestedPolicy: "preserve_consistently",
    confidence: "medium",
    occurrences: [{ chapterId: "ch09-the-mock-turtle-s-story", evidenceQuote: "they saw the Mock Turtle in the distance" }],
  },
  {
    canonicalForm: "Gryphon",
    category: "character",
    meaning: "A mythological creature who escorts Alice to the Mock Turtle.",
    pronunciation: "GRIF-in",
    pronunciationConfidence: "high",
    suggestedPolicy: "preserve_consistently",
    confidence: "high",
    occurrences: [{ chapterId: "ch09-the-mock-turtle-s-story", evidenceQuote: "a Gryphon, lying fast asleep" }],
  },
];

async function main() {
  mkdirSync(outDir, { recursive: true });

  section("STEP 1 — INGEST: parse the manuscript, extract metadata automatically");
  const aliceText = readFileSync(path.join(root, "tests/fixtures/alice.txt"), "utf8");
  const manuscript = parseManuscript(aliceText);
  console.log(`Title:     ${manuscript.metadata.title}  (extracted, not asked of the user)`);
  console.log(`Author:    ${manuscript.metadata.author}`);
  console.log(`Language:  ${manuscript.metadata.sourceLanguage}`);
  console.log(`Chapters:  ${manuscript.chapters.length}`);
  const totalBlocks = manuscript.chapters.reduce((sum, c) => sum + c.blocks.length, 0);
  const verseBlocks = manuscript.chapters.reduce((sum, c) => sum + c.blocks.filter((b) => b.kind === "verse").length, 0);
  const dialogueBlocks = manuscript.chapters.reduce((sum, c) => sum + c.blocks.filter((b) => b.kind === "dialogue").length, 0);
  console.log(`Blocks:    ${totalBlocks} total (${verseBlocks} verse, ${dialogueBlocks} dialogue-classified)`);
  console.log(`Source hash: ${manuscript.sourceHash}`);

  section("STEP 2 — EXTRACT: term base + style note via the LLM provider abstraction");
  const useRealProvider = Boolean(process.env.ANTHROPIC_API_KEY);
  const provider = useRealProvider ? new AnthropicProvider() : new MockLlmProvider(MOCK_TERMS);
  console.log(`Provider: "${provider.name}"${useRealProvider ? "" : "  (ANTHROPIC_API_KEY not set -- using a fixed mock grounded in real quotes from the fixture; set the key to see AnthropicProvider run instead, same pipeline code either way)"}`);

  const { terms: suggestedTerms, warnings } = await extractTermCandidates(provider, manuscript);
  console.log(`\n${suggestedTerms.length} term candidate(s) survived evidence verification against the actual manuscript text:`);
  for (const t of suggestedTerms) {
    console.log(`  - ${t.canonicalForm} (${t.category}, ${t.suggestedPolicy}, confidence=${t.confidence}) [status: ${t.status}]`);
  }
  if (warnings.length > 0) {
    console.log(`\n${warnings.length} warning(s) from extraction (dropped/downgraded candidates):`);
    for (const w of warnings) console.log(`  - ${w.canonicalForm}: ${w.reason}`);
  }

  const styleNote = await generateStyleNote(provider, manuscript);
  console.log(`\nStyle note (status: ${styleNote.status}):`);
  console.log(`  Register: ${styleNote.register}`);
  console.log(`  Tone:     ${styleNote.tone}`);

  section("STEP 3 — HUMAN REVIEW: confirm suggested terms (simulated rights-manager sign-off)");
  const confirmedTerms: TermCandidate[] = suggestedTerms.map((t) => confirmTerm(t, "demo-rights-manager@example.com"));
  for (const t of confirmedTerms) console.log(`  CONFIRMED: ${t.canonicalForm}  (reviewed by ${t.reviewedBy})`);
  const allTermsAfterReview = confirmedTerms; // in this demo every suggestion is confirmed; a real UI would let some be rejected/edited instead
  const confirmedRules = buildDoNotTranslateRules(allTermsAfterReview);
  console.log(`\n${confirmedRules.length} enforceable do-not-translate rule(s) built from confirmed terms.`);

  section("STEP 4 — BUILD PACKET: the actual translator handoff artifact");
  const packet = buildTranslationPacket({
    manuscript,
    allTerms: allTermsAfterReview,
    confirmedRules,
    styleNote,
    targetLanguage: "Spanish",
    targetLocale: "Spain",
  });
  console.log(`Clean source HTML: ${packet.cleanSourceHtml.length.toLocaleString()} chars, ${(packet.cleanSourceHtml.match(/data-chunk-id/g) ?? []).length} chunks`);
  console.log(`Term base entries: ${packet.termBase.length}`);
  console.log(`Formatting guidance rules: ${packet.formattingGuidance.length}`);
  writeFileSync(path.join(outDir, "translation-packet.json"), JSON.stringify(packet, null, 2));
  console.log(`Wrote demo-output/translation-packet.json`);

  section("STEP 5 — RETURNED TRANSLATION: verify against the term base (chapter by chapter)");
  // Hand-translated (Spanish) for three chapters. Chapter I deliberately
  // mistranslates the confirmed do-not-translate term "Dinah" as "Dina" --
  // this is the flagship scenario the whole packet-verification pipeline
  // exists to catch. Chapters VI and IX are translated cleanly and should
  // PASS, to show the report isn't just always red.
  const translatedChapters: Chapter[] = [
    {
      id: "tch01",
      index: 1,
      title: "Por la madriguera del conejo",
      blocks: [
        {
          id: "tch01-b0",
          kind: "paragraph",
          text: "Alice empezaba a cansarse de estar sentada junto a su hermana en la orilla, sin nada que hacer.",
          spans: [],
          hasEmphasis: false,
        },
        {
          id: "tch01-b1",
          kind: "paragraph",
          text: "De pronto un White Rabbit de ojos rosados pasó corriendo cerca de ella.",
          spans: [],
          hasEmphasis: false,
        },
        {
          id: "tch01-b2",
          kind: "paragraph",
          // Deliberate violation: "Dinah" (confirmed do_not_translate) rendered as "Dina".
          text: "Dina era la gata. Espero que se acuerden de su platito de leche a la hora del té.",
          spans: [],
          hasEmphasis: false,
        },
      ],
    },
    {
      id: "tch06",
      index: 6,
      title: "Cerdo y pimienta",
      blocks: [
        {
          id: "tch06-b0",
          kind: "dialogue",
          text: "«Es un Cheshire cat», dijo la Duquesa, «y por eso. ¡Cerdo!»",
          spans: [],
          hasEmphasis: false,
        },
      ],
    },
    {
      id: "tch09",
      index: 9,
      title: "La historia de la Mock Turtle",
      blocks: [
        {
          id: "tch09-b0",
          kind: "paragraph",
          text: "No habían ido muy lejos cuando vieron al Gryphon, dormido profundamente al sol.",
          spans: [],
          hasEmphasis: false,
        },
        {
          id: "tch09-b1",
          kind: "paragraph",
          text: "No habían ido muy lejos antes de ver a la Mock Turtle a lo lejos, sentada triste y sola sobre una roca.",
          spans: [],
          hasEmphasis: false,
        },
      ],
    },
  ];

  const sourceChaptersForQa: Chapter[] = [
    {
      id: "ch01-down-the-rabbit-hole",
      index: 1,
      title: "Down the Rabbit-Hole",
      blocks: (() => {
        const full = manuscript.chapters.find((c) => c.title === "Down the Rabbit-Hole")!;
        return [
          full.blocks.find((b) => b.text.includes("nothing to do"))!,
          full.blocks.find((b) => b.text.includes("a White Rabbit with pink eyes ran"))!,
          full.blocks.find((b) => b.text.includes("Dinah was the cat"))!,
        ];
      })(),
    },
    {
      id: "ch06-pig-and-pepper",
      index: 6,
      title: "Pig and Pepper",
      blocks: [manuscript.chapters.find((c) => c.title === "Pig and Pepper")!.blocks.find((b) => b.text.includes("Cheshire cat"))!],
    },
    {
      id: "ch09-the-mock-turtle-s-story",
      index: 9,
      title: "The Mock Turtle’s Story",
      blocks: (() => {
        const full = manuscript.chapters.find((c) => c.title === "The Mock Turtle’s Story")!;
        return [full.blocks.find((b) => b.text.includes("a Gryphon"))!, full.blocks.find((b) => b.text.includes("saw the Mock Turtle"))!];
      })(),
    },
  ];
  // Note: for demo speed and a clean 1:1 alignment, sourceChaptersForQa above
  // is a matched EXCERPT (the specific sentences being translated below),
  // not the full chapter -- the full manuscript.chapters (used in Steps 1-4
  // for extraction/packet-building) is unabridged. The alignment and
  // verification engines themselves are exercised against full, differently-
  // shaped chapters in src/align and src/rules' own test suites.

  const chapterAlignments = alignManuscripts(sourceChaptersForQa, translatedChapters);
  const findings = verifyProtectedTerms({
    rules: confirmedRules,
    allTerms: allTermsAfterReview,
    sourceChapters: sourceChaptersForQa,
    translatedChapters,
    chapterAlignments,
  });
  const qaReport = buildQaReport(sourceChaptersForQa, confirmedRules, findings);
  console.log(renderQaReportAsText(qaReport));

  if (findings.length > 0) {
    console.log("\nFinding detail:");
    for (const f of findings) {
      console.log(`\n  [${f.severity.toUpperCase()}] ${f.category} — ${f.chapterTitle} (rule status: ${f.ruleStatus})`);
      console.log(`    Expected: ${f.expected}`);
      console.log(`    Found:    ${f.actual}`);
      console.log(`    Rule:     ${f.ruleDescription}`);
      console.log(`    Action:   ${f.recommendedAction}`);
    }
  }
  writeFileSync(path.join(outDir, "qa-report.json"), JSON.stringify(qaReport, null, 2));
  console.log(`\nWrote demo-output/qa-report.json`);

  section("STEP 6 — DOCUMENT INTEGRITY: the 'change only the title' invariant");
  const before = readFileSync(path.join(root, "tests/fixtures/alice-superdocs-before.html"), "utf8");
  const passAfter = readFileSync(path.join(root, "tests/fixtures/alice-superdocs-after-title-only-PASS.html"), "utf8");
  const failAfter = readFileSync(path.join(root, "tests/fixtures/alice-superdocs-after-title-only-FAIL.html"), "utf8");

  const passResult = checkIntegrity(diffDocumentBodies(before, passAfter), [], { allowed: [{ kind: "text", location: "chunk-title" }] });
  console.log(`Scoped title-heading edit (correct):   pass=${passResult.pass}  changes=${passResult.actualChangeCount}`);

  const failResult = checkIntegrity(diffDocumentBodies(before, failAfter), [], { allowed: [{ kind: "text", location: "chunk-title" }] });
  console.log(`Chat-based edit that also drifted body: pass=${failResult.pass}  unexpected=${failResult.unexpectedChanges.map((c) => c.location).join(", ")}`);

  const renameMetadataChanges = diffMetadata({ title: "Alice's Adventures in Wonderland" }, { title: "Alice's Adventures in Wonderland: Special Edition" });
  const renameResult = checkIntegrity(diffDocumentBodies(before, before), renameMetadataChanges, { allowed: [{ kind: "metadata", location: "title" }] });
  console.log(`Rename via PATCH /v1/documents/{id} (correct): pass=${renameResult.pass}  changes=${renameResult.actualChangeCount}`);

  section("STEP 7 — SUPERDOCS: live integration (credentialed smoke test only)");
  if (!process.env.SUPERDOCS_API_KEY) {
    console.log("SUPERDOCS_API_KEY is not set -- live verification remains explicitly PENDING.");
    console.log("The local UI still exposes the full server-side integration: connection check, proposed changes, approval and DOCX export.");
  } else {
    const integration = new SuperDocsIntegration();
    const state = await integration.prepareDocument(
      emptySuperDocsState(),
      packet.cleanSourceHtml,
      "alice-clean-source.html",
      "Prepare this manuscript for translation while preserving approved terminology, semantic formatting, chapter structure and translator guidance. Keep edits narrowly scoped and reviewable.",
    );
    console.log(`  SuperDocs status: ${state.status}`);
    console.log(`  session_id: ${state.sessionId ?? "n/a"}`);
    console.log(`  job_id: ${state.jobId ?? "n/a"}`);
    console.log(`  proposed changes: ${state.pendingChanges.length}`);
    if (state.status === "awaiting_approval" && state.pendingChanges.length) {
      const decisions = state.pendingChanges.map((change) => ({ changeId: String(change.changeId ?? change.change_id), approved: true }));
      const approved = await integration.approve(state, decisions);
      console.log(`  approval result: ${approved.status}`);
      if (approved.sessionId) {
        const exported = await integration.exportDocx(approved);
        const exportPath = path.join(outDir, "superdocs-reviewed.docx");
        writeFileSync(exportPath, Buffer.from(await exported.arrayBuffer()));
        console.log(`  exported: ${path.relative(root, exportPath)}`);
      }
    }
  }

  section("DONE");
  console.log(`Artifacts written to ${path.relative(root, outDir)}/`);
}

main().catch((err) => {
  console.error("\nDemo failed:", err);
  process.exitCode = 1;
});
