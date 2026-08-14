/**
 * QualityChecks.gs
 * -----------------------------------------------------------------------
 * Bonus, non-blocking signal: rough plain-text length comparison between
 * the exported .docx and the original source, to catch gross content
 * loss (e.g. the AI silently dropping a whole section) - see the task
 * doc's instruction rules in AsyncJobs.gs for the real bugs this is
 * meant to catch. This is a heuristic, not a guarantee - see the
 * defensive try/catch at every call site.
 *
 * CURRENT LIMITATION (logged honestly, see PROGRESS.md): this only
 * works when the source is a real .docx, since it works by unzipping
 * the file and reading word/document.xml. It is currently only run for
 * Drive-sourced jobs, where the original file is still addressable by
 * ID at finish time. For non-.docx sources (.doc, .odt, .rtf, scanned
 * PDF) and for Gmail-sourced jobs (where only the attachment's name,
 * not its bytes, survives into the stored job), the check is skipped
 * rather than silently comparing the wrong two things.
 * -----------------------------------------------------------------------
 */

/**
 * Unzips a .docx blob (docx is a zip container), reads
 * word/document.xml, strips XML tags, and returns the plain-text
 * character count. Throws on non-.docx bytes - callers treat this
 * whole check as non-fatal.
 */
function extractDocxPlainTextLength(docxBlob) {
  const files = Utilities.unzip(docxBlob);
  const documentXmlFile = files.filter(function (f) {
    return f.getName() === "word/document.xml";
  })[0];

  if (!documentXmlFile) {
    throw new Error("word/document.xml not found in exported .docx");
  }

  const xml = documentXmlFile.getDataAsString("UTF-8");
  const plainText = xml
    .replace(/<[^>]+>/g, "") // strip all XML tags
    .replace(/\s+/g, " ") // collapse whitespace
    .trim();

  return plainText.length;
}

/**
 * Compares input vs output text length and returns a warning string
 * (empty string if nothing looks wrong). Threshold is deliberately
 * generous (70%) since restyling can legitimately shorten some
 * boilerplate; this is meant to catch gross loss, not nitpick.
 */
function buildContentLossWarning(inputTextLength, outputTextLength) {
  if (
    typeof inputTextLength !== "number" ||
    typeof outputTextLength !== "number" ||
    inputTextLength <= 0
  ) {
    return ""; // nothing reliable to compare against - stay silent, not wrong
  }

  const ratio = outputTextLength / inputTextLength;
  if (ratio < 0.7) {
    const pctLost = Math.round((1 - ratio) * 100);
    return (
      "\n\n\u26A0\uFE0F Content check: the output has roughly " +
      pctLost +
      "% less text than the original. Please review it before relying on it."
    );
  }
  return "";
}
