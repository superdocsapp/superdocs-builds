/**
 * GitHub Actions workflow commands.
 *
 * A build-pipeline check earns its place by putting the finding on the line of
 * the file that carries it, in the pull request, rather than in a log a person
 * has to open.
 */

const LEVELS = {
  error: 'error',
  warning: 'warning',
  info: 'notice',
  notice: 'notice',
};

export function formatGithub(report, options = {}) {
  const file = options.file || '';
  const lines = [];

  for (const finding of report.findings) {
    const level = LEVELS[finding.severity] || 'notice';
    const properties = [];
    if (file) properties.push(`file=${escapeProperty(file)}`);
    if (finding.locator) {
      properties.push(`line=${finding.locator.line}`);
      properties.push(`col=${finding.locator.column}`);
    }
    properties.push(`title=${escapeProperty(`${finding.rule}${finding.id ? ` (${finding.id})` : ''}`)}`);

    const body = [
      finding.cause,
      finding.locator ? `block: ${finding.locator.tag}[${finding.locator.blockIndex}] at ${finding.locator.path}` : '',
      finding.locator && finding.locator.preview ? `text: "${finding.locator.preview}"` : '',
      finding.counterpart ? `after: ${finding.counterpart.tag} at line ${finding.counterpart.line}` : '',
      ...finding.evidence,
      `confidence: ${finding.confidence}`,
    ].filter(Boolean).join('\n');

    lines.push(`::${level} ${properties.join(',')}::${escapeData(body)}`);
  }

  if (report.findings.length === 0) {
    lines.push('::notice::block identity check clean: every identifier survived the round trip');
  }
  return lines.join('\n');
}

function escapeData(value) {
  return String(value).replace(/%/g, '%25').replace(/\r/g, '%0D').replace(/\n/g, '%0A');
}

function escapeProperty(value) {
  return escapeData(value).replace(/:/g, '%3A').replace(/,/g, '%2C');
}
