import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { parseManuscript } from "../src/ingest/parseManuscript.js";
import { MockLlmProvider } from "../src/extract/llmProvider.js";
import { prepareRun, validateReturnedTranslation, exportArtifacts } from "../src/workflow/workflow.js";
import type { RawTermSuggestion } from "../src/extract/llmProvider.js";

const root = process.cwd();
const source = parseManuscript(readFileSync(join(root,"examples/second-manuscript/source.txt"),"utf8"));
const bad = parseManuscript(readFileSync(join(root,"examples/second-manuscript/translated-bad.txt"),"utf8"));
const good = parseManuscript(readFileSync(join(root,"examples/second-manuscript/translated-good.txt"),"utf8"));
const terms: RawTermSuggestion[] = [
 {canonicalForm:"Veyra",category:"place",meaning:"The valley named Veyra.",pronunciation:null,pronunciationConfidence:null,suggestedPolicy:"do_not_translate",confidence:"high",occurrences:[{chapterId:source.chapters[0]!.id,evidenceQuote:"The word _Veyra_ was written"}]},
 {canonicalForm:"Emberglass",category:"object",meaning:"A named object carried by Mira.",pronunciation:null,pronunciationConfidence:null,suggestedPolicy:"do_not_translate",confidence:"high",occurrences:[{chapterId:source.chapters[0]!.id,evidenceQuote:"carrying the Emberglass"}]},
 {canonicalForm:"Night Ledger",category:"object",meaning:"A protected title in the Bell Archive.",pronunciation:null,pronunciationConfidence:null,suggestedPolicy:"do_not_translate",confidence:"high",occurrences:[{chapterId:source.chapters[1]!.id,evidenceQuote:"asked for the Night Ledger"}]},
];
const provider = new MockLlmProvider(terms);
const run = await prepareRun(source, provider, "Spanish", true);
const badReport = validateReturnedTranslation(run.id,bad.chapters);
const goodReport = validateReturnedTranslation(run.id,good.chapters);
const out=join(root,"demo-output-second"); mkdirSync(out,{recursive:true}); const exported=exportArtifacts(run.id); writeFileSync(join(out,"qa-bad.md"),JSON.stringify(badReport,null,2)); writeFileSync(join(out,"qa-good.md"),JSON.stringify(goodReport,null,2)); writeFileSync(join(out,"packet-artifacts.json"),JSON.stringify(exported.artifacts,null,2));
console.log(`Second manuscript run: ${run.id}`); console.log(`Bad translation findings: ${badReport.totalFindings}`); console.log(`Good translation findings: ${goodReport.totalFindings}`); if(badReport.totalFindings<1) throw new Error("Second manuscript bad case did not fail"); if(goodReport.totalFindings!==0) throw new Error("Second manuscript good case did not pass");
