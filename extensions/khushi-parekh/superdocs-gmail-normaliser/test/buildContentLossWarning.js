/**
 * Node-testable copy of QualityChecks.gs -> buildContentLossWarning().
 * Same duplication reasoning as parseProposedChanges.js - see that
 * file's header comment.
 */
function buildContentLossWarning(inputTextLength, outputTextLength) {
  if (
    typeof inputTextLength !== "number" ||
    typeof outputTextLength !== "number" ||
    inputTextLength <= 0
  ) {
    return "";
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

module.exports = { buildContentLossWarning };
