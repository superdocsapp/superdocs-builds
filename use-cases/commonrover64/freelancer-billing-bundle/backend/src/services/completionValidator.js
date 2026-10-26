import JSZip from "jszip";

// Docx files are zip archives. The visible text lives inside word/document.xml.
// We check that every expected value actually appears in the final text,
// instead of trusting the job's own "completed" status.
export async function extractTextFromDocx(buffer) {
    const zip = await JSZip.loadAsync(buffer);
    const xml = await zip.file("word/document.xml").async("string");

    return xml.replace(/<[^>]+>/g, " ");
}

// Checks that every expected value string appears somewhere in the document text.
// Returns which ones are missing, so a failure is specific, not just a boolean.
export async function validateCompletion(buffer, expectedValues) {
    const text = await extractTextFromDocx(buffer);

    const missing = expectedValues.filter(
        (value) => !text.includes(String(value)),
    );

    return {
        isComplete: missing.length === 0,
        missing,
    };
}
