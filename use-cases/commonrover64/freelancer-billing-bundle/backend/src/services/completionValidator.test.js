import { describe, it, expect } from "vitest";
import {
    validateCompletion,
    extractTextFromDocx,
} from "./completionValidator.js";
import JSZip from "jszip";

// builds a minimal fake docx buffer containing the given text, so we can
// test validateCompletion without needing a real SuperDocs export.
async function fakeDocxBuffer(text) {
    const zip = new JSZip();
    zip.file(
        "word/document.xml",
        `<w:document><w:body><w:p><w:r><w:t>${text}</w:t></w:r></w:p></w:body></w:document>`,
    );
    return zip.generateAsync({ type: "nodebuffer" });
}

describe("validateCompletion", () => {
    it("passes when every expected value is present", async () => {
        const buffer = await fakeDocxBuffer("Client: Acme Co, Total: 64000");
        const result = await validateCompletion(buffer, ["Acme Co", "64000"]);
        expect(result.isComplete).toBe(true);
        expect(result.missing).toEqual([]);
    });

    it("reports exactly which values are missing", async () => {
        // Regression test for a real bug found during development: a
        // SuperDocs job reported status "completed" while several fields
        // were silently never filled in. This is the check that would have
        // caught it before trusting the job's own status.
        const buffer = await fakeDocxBuffer("Client: TBD, Total: TBD");
        const result = await validateCompletion(buffer, ["Acme Co", "64000"]);
        expect(result.isComplete).toBe(false);
        expect(result.missing).toEqual(["Acme Co", "64000"]);
    });
});
