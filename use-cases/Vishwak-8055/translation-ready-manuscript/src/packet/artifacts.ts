import type { TranslationPacket, Finding, TranslationQaReport } from "../types.js";

export interface PacketArtifacts {
  cleanSourceHtml: string;
  sourceMetadataMarkdown: string;
  termBaseJson: string;
  termBaseMarkdown: string;
  doNotTranslateText: string;
  pronunciationMarkdown: string;
  meaningMarkdown: string;
  styleGuideMarkdown: string;
  formattingMarkdown: string;
  translationInstructionsMarkdown: string;
  qaReportMarkdown: string;
}

export function renderPacketArtifacts(packet: TranslationPacket): PacketArtifacts {
  const termBaseMarkdown = [
    `# Term Base`, ``,
    `Manuscript: ${packet.manuscriptTitle}`, `Target language: ${packet.targetLanguage}`, ``,
    `| Term | Category | Policy | Status | Confidence | Chapters |`,
    `|---|---|---|---|---|---|`,
    ...packet.termBase.map(t => `| ${escapeMd(t.confirmedOverride?.canonicalForm ?? t.canonicalForm)} | ${t.category} | ${t.confirmedOverride?.policy ?? t.suggestedPolicy} | ${t.status} | ${t.confidence} | ${t.occurrences.map(o => o.chapterTitle).filter((v,i,a)=>a.indexOf(v)===i).join(", ")} |`),
    ``,
    `## Evidence`, ``,
    ...packet.termBase.flatMap(t => [`### ${t.confirmedOverride?.canonicalForm ?? t.canonicalForm}`, `- Meaning: ${t.meaning || "Requires human confirmation"}`, `- Pronunciation: ${t.pronunciation.value ?? "Requires human confirmation"}`, ...t.occurrences.slice(0,3).map(o => `- Evidence (${o.chapterTitle}): “${o.evidenceQuote}”`), ``]),
  ].join("\n");
  const dnt = packet.doNotTranslateRules.map(r => r.canonicalForm).join("\n");
  const sourceMetadataMarkdown = ["# Source Metadata", "", `- Manuscript: ${packet.manuscriptTitle}`, `- Filename: ${packet.sourceMetadata.filename ?? "Not available"}`, `- Format: ${packet.sourceMetadata.format ?? "Not available"}`, `- Author: ${packet.sourceMetadata.author ?? "Not available"}`, `- Source language: ${packet.sourceMetadata.sourceLanguage ?? "Not confidently determined"}`, `- Source hash: ${packet.sourceHash}`].join("\n");
  const pronunciation = ["# Pronunciation Notes", "", ...packet.termBase.map(t => `- **${t.canonicalForm}** — ${t.pronunciation.value ?? "Requires human confirmation"} (${t.pronunciation.confidence ?? "unknown"})`)].join("\n");
  const meaning = ["# Meaning / Context Notes", "", ...packet.termBase.map(t => `## ${t.canonicalForm}\n${t.meaning || "Insufficient source evidence; human confirmation required."}\n\nEvidence:\n${t.occurrences.slice(0,3).map(o => `- ${o.chapterTitle}: “${o.evidenceQuote}”`).join("\n")}`)].join("\n\n");
  const style = ["# Style / Voice Guide", "", `- Register: ${packet.styleNote.register}`, `- Narrative voice: ${packet.styleNote.narrativeVoice}`, `- Dialogue: ${packet.styleNote.dialogue}`, `- Tone: ${packet.styleNote.tone}`, `- Wordplay: ${packet.styleNote.wordplay}`, `- Verse: ${packet.styleNote.verse}`, `- Formatting: ${packet.styleNote.formatting}`, `- Translation considerations: ${packet.styleNote.translationConsiderations}`, `- Status: ${packet.styleNote.status}`, ...(packet.styleNote.additionalNotes.length ? ["", ...packet.styleNote.additionalNotes.map(n => `- ${n}`)] : [])].join("\n");
  const formatting = ["# Formatting Semantics", "", ...packet.formattingGuidance.map(r => `## ${r.formatting}\n- Location: ${r.source.chapterTitle}, ${r.source.blockIndex >= 0 ? `block ${r.source.blockIndex + 1}` : "chapter heading"}\n- Meaning: ${r.meaning}\n- Translation requirement: ${r.translationRequirement}\n- Evidence: “${r.source.evidenceQuote}”`)].join("\n\n");
  const instructions = ["# Translation Instructions", "", "1. Preserve confirmed do-not-translate terms exactly unless an approved variant is explicitly documented.", "2. Preserve chapter and section structure.", "3. Preserve formatting that is documented as semantic.", "4. Preserve the manuscript's register, voice and dialogue conventions.", "5. Do not invent meaning or pronunciation for terms whose evidence is insufficient.", "6. Flag ambiguous terminology for human review rather than guessing.", "", "## Protected terms", dnt || "None confirmed yet."].join("\n");
  return { cleanSourceHtml: packet.cleanSourceHtml, sourceMetadataMarkdown, termBaseJson: JSON.stringify(packet.termBase, null, 2), termBaseMarkdown, doNotTranslateText: dnt + (dnt ? "\n" : ""), pronunciationMarkdown: pronunciation, meaningMarkdown: meaning, styleGuideMarkdown: style, formattingMarkdown: formatting, translationInstructionsMarkdown: instructions, qaReportMarkdown: "" };
}

export function renderQaReportMarkdown(report: TranslationQaReport): string {
  const lines = ["# Translation QA Report", "", `Protected terms: ${report.totalProtectedTerms}`, `Passed: ${report.totalPassed}`, `Findings: ${report.totalFindings}`, "", "## Chapter summary", "", "| Chapter | Status | Findings |", "|---|---|---:|", ...report.chapters.map(c => `| ${escapeMd(c.chapterTitle)} | ${c.status.toUpperCase()} | ${c.findingCount} |`), "", "## Evidence", ""];
  for (const f of report.findings) {
    lines.push(`### ${f.chapterTitle} — ${f.expected}`);
    lines.push(`- Severity: ${f.severity}`);
    lines.push(`- Status: ${f.ruleStatus}`);
    lines.push(`- Expected: ${f.expected}`);
    lines.push(`- Actual: ${f.actual}`);
    lines.push(`- Rule: ${f.ruleDescription}`);
    lines.push(`- Source evidence: “${f.sourceLocation.evidenceQuote}”`);
    if (f.translatedLocation) lines.push(`- Returned evidence: “${f.translatedLocation.evidenceQuote}”`);
    lines.push(`- Confidence: ${f.confidence}`, `- Recommended action: ${f.recommendedAction}`, "");
  }
  return lines.join("\n");
}
function escapeMd(s: string): string { return s.replace(/\|/g, "\\|").replace(/\n/g, " "); }
