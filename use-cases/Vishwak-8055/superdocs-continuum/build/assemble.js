'use strict';
/**
 * Assembles src/data.js + src/engine.js + src/ui.jsx into one self-contained
 * .jsx artifact, because the target runtime (a chat-based single-file React
 * artifact) does not support local relative imports across files.
 *
 * This is a mechanical concatenation, not a hand-copy: the tested modules
 * in src/engine.js and src/data.js are the single source of truth, and this
 * script is what keeps the shipped artifact byte-identical to what the test
 * suite actually exercised.
 *
 * Usage:
 *   node build/assemble.js                  -> writes dist/document_os.jsx
 *   node build/assemble.js --check-only      -> verifies it assembles without writing
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const OUT = path.join(ROOT, 'dist', 'document_os.jsx');

function stripModuleBoilerplate(src) {
  return src
    .replace(/^'use strict';\n/, '')
    .replace(/\nmodule\.exports\s*=\s*\{[\s\S]*?\};\s*$/, '\n');
}

function main() {
  const dataSrc = stripModuleBoilerplate(fs.readFileSync(path.join(ROOT, 'src/data.js'), 'utf8'));
  const engineSrc = stripModuleBoilerplate(fs.readFileSync(path.join(ROOT, 'src/engine.js'), 'utf8'));
  const uiSrc = fs.readFileSync(path.join(ROOT, 'src/ui.jsx'), 'utf8');

  const importLines = [];
  const bodyLines = [];
  let inImport = false;
  uiSrc.split('\n').forEach((line) => {
    if (!inImport && /^import\b/.test(line)) {
      inImport = true;
    }
    if (inImport) {
      importLines.push(line);
      if (/;\s*$/.test(line)) inImport = false;
    } else {
      bodyLines.push(line);
    }
  });

  const assembled = [
    importLines.join('\n'),
    '',
    '/* ================== inlined from src/data.js (tested, see tests/engine.test.js) ================== */',
    dataSrc.trim(),
    '',
    '/* ================== inlined from src/engine.js (tested, see tests/*.test.js) ================== */',
    engineSrc.trim(),
    '',
    bodyLines.join('\n').trim(),
    '',
  ].join('\n');

  if (process.argv.includes('--check-only')) {
    if (!assembled.includes('export default function SuperDocsRealityEngine')) {
      console.error('CHECK FAILED: default export not found in assembled output');
      process.exit(1);
    }
    console.log('assemble check OK —', assembled.length, 'chars would be written');
    return;
  }

  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  fs.writeFileSync(OUT, assembled);
  console.log('wrote', OUT, '—', assembled.length, 'chars');
}

main();
