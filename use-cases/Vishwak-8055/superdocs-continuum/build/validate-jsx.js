'use strict';
/**
 * Parses src/ui.jsx and the assembled dist/document_os.jsx with an actual
 * JSX-capable parser (Babel) and fails loudly on a real syntax error.
 * `node --check` cannot do this on its own — it does not understand JSX —
 * so this is the step that makes "the build passed" a claim backed by
 * something that actually reads the JSX.
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

const ROOT = path.join(__dirname, '..');
const targets = [
  path.join(ROOT, 'src/ui.jsx'),
  path.join(ROOT, 'dist/document_os.jsx'),
];

let failed = false;
targets.forEach((file) => {
  if (!fs.existsSync(file)) {
    console.error(`MISSING: ${file}`);
    failed = true;
    return;
  }
  const code = fs.readFileSync(file, 'utf8');
  try {
    babel.transformSync(code, {
      presets: ['@babel/preset-react'],
      filename: file,
      babelrc: false,
      configFile: false,
    });
    console.log(`OK   ${path.relative(ROOT, file)} (${code.length} chars, parses as valid JSX)`);
  } catch (err) {
    console.error(`FAIL ${path.relative(ROOT, file)}`);
    console.error(err.message);
    failed = true;
  }
});

if (failed) {
  console.error('\nJSX validation failed.');
  process.exit(1);
}
console.log('\nJSX validation passed for all targets.');
