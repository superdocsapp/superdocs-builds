import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';
import { parseUploadedDocument } from '../services/documentParser';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * Regression test for a real bug hit during manual testing: pdf-parse v2.x
 * changed its public API from a callable function (v1.x: `pdfParse(buffer)`)
 * to a class (`new PDFParse({data}).getText()`). The old code called it as a
 * function, which threw "pdfParse is not a function" on every real PDF
 * upload -- something the previous mocked tests never caught, because they
 * never actually ran pdf-parse against real bytes.
 *
 * This test deliberately uses a REAL PDF file (fixtures/minimal-test.pdf,
 * a hand-built minimal valid PDF, not a mock) run through the actual
 * parseUploadedDocument() function, so a future dependency bump or refactor
 * that reintroduces this class-vs-function mismatch fails a test instead of
 * failing silently until someone uploads a real file in the browser.
 */
export async function runDocumentParserTests() {
  console.log('\n--- Document Parser Tests (real PDF, not mocked) ---');
  let passed = 0;
  let failed = 0;

  function assert(condition: boolean, testName: string) {
    if (condition) {
      console.log(`  ✅ [PASS] ${testName}`);
      passed++;
    } else {
      console.error(`  ❌ [FAIL] ${testName}`);
      failed++;
    }
  }

  const fixturePath = path.join(__dirname, 'fixtures', 'minimal-test.pdf');
  const pdfBuffer = fs.readFileSync(fixturePath);

  try {
    const result = await parseUploadedDocument(pdfBuffer, 'minimal-test.pdf', 'application/pdf');
    assert(result.fileType === 'pdf', 'parseUploadedDocument identifies a real PDF as fileType "pdf"');
    assert(result.textContent.includes('Hello SuperDocs Test PDF'),
      'parseUploadedDocument extracts real text from a real PDF via pdf-parse v2.x (regression test for "pdfParse is not a function")');
  } catch (err: any) {
    assert(false, `parseUploadedDocument should not throw on a valid PDF, but got: ${err.message}`);
  }

  // Empty buffer should throw a clear error, not crash the parser internals.
  try {
    await parseUploadedDocument(Buffer.alloc(0), 'empty.pdf', 'application/pdf');
    assert(false, 'parseUploadedDocument should throw on a 0-byte file');
  } catch (err: any) {
    assert(err.message.includes('empty'), 'parseUploadedDocument gives a clear error for a 0-byte file');
  }

  // Corrupted (non-PDF bytes with .pdf extension) should throw a descriptive error, not "is not a function".
  try {
    await parseUploadedDocument(Buffer.from('this is not a real pdf'), 'fake.pdf', 'application/pdf');
    assert(false, 'parseUploadedDocument should throw on corrupted PDF bytes');
  } catch (err: any) {
    assert(
      !err.message.includes('is not a function'),
      'parseUploadedDocument fails with a descriptive parse error on corrupted input, not an API-shape crash'
    );
  }

  console.log(`\n  Document parser tests: ${passed} passed, ${failed} failed.`);
  return { passed, failed };
}
