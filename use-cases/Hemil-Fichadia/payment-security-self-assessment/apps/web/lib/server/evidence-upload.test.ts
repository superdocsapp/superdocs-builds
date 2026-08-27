import assert from "node:assert/strict";
import test from "node:test";
import {
  EvidenceUploadError,
  extractTextEvidenceFiles,
  MAX_UPLOAD_FILE_BYTES,
  validateEvidenceFiles,
} from "./evidence-upload.ts";

const textFile = (name: string, text: string) => ({ name, type: "text/plain", size: text.length, text: async () => text });

test("validates and extracts plain-text evidence", async () => {
  const documents = await extractTextEvidenceFiles([textFile("identity.txt", "Administrator accounts currently require MFA.")]);
  assert.deepEqual(documents, [{ id: "upload-1", name: "identity.txt", text: "Administrator accounts currently require MFA." }]);
});

test("rejects unsupported evidence formats", () => {
  assert.throws(() => validateEvidenceFiles([{ name: "report.pdf", type: "application/pdf", size: 12 }]), EvidenceUploadError);
});

test("enforces file count and size limits", () => {
  assert.throws(() => validateEvidenceFiles(Array.from({ length: 4 }, (_, index) => ({ name: `${index}.txt`, type: "text/plain", size: 1 }))), EvidenceUploadError);
  assert.throws(() => validateEvidenceFiles([{ name: "large.txt", type: "text/plain", size: MAX_UPLOAD_FILE_BYTES + 1 }]), EvidenceUploadError);
});
