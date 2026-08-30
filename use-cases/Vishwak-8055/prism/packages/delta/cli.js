#!/usr/bin/env node
// @ts-check
import { writeFile } from 'node:fs/promises';
import { compareFiles } from './src/index.js';

function printHuman(report) {
  const { summary, changes, baseFingerprint, targetFingerprint } = report;
  console.log('PRISM DELTA — material change report');
  console.log('='.repeat(40));
  console.log(`base fingerprint   : ${baseFingerprint.slice(0, 12)}...`);
  console.log(`target fingerprint : ${targetFingerprint.slice(0, 12)}...`);
  console.log(`total changes      : ${summary.totalChanges}`);
  console.log(`  material         : ${summary.materialChangeCount}`);
  console.log(`  review-required  : ${summary.reviewRequiredCount}`);
  console.log(`  cosmetic/minor   : ${summary.cosmeticOnlyCount}`);
  console.log('');
  if (summary.totalChanges === 0) {
    console.log('NO MATERIAL CHANGE.');
    return;
  }
  for (const [i, change] of changes.entries()) {
    console.log(`[${i + 1}] ${change.type}`);
    for (const f of change.findings) {
      console.log(`    - (${f.category}/${f.materiality}) ${f.why}`);
    }
  }
}

async function main() {
  const [, , basePath, targetPath, ...rest] = process.argv;
  if (!basePath || !targetPath) {
    console.error('Usage: node cli.js <base.docx> <target.docx> [--json out.json]');
    process.exit(1);
  }
  const report = await compareFiles(basePath, targetPath);
  printHuman(report);

  const jsonFlagIndex = rest.indexOf('--json');
  if (jsonFlagIndex !== -1 && rest[jsonFlagIndex + 1]) {
    const outPath = rest[jsonFlagIndex + 1];
    await writeFile(outPath, JSON.stringify(report, null, 2), 'utf-8');
    console.log(`\nFull JSON report written to ${outPath}`);
  }
}

main().catch((err) => {
  console.error('PRISM DELTA failed:', err);
  process.exit(1);
});
