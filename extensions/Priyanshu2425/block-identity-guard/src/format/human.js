/**
 * The human report.
 *
 * Every line answers one of four questions: which block, where it is, what
 * happened to it, and how sure the tool is. A report that cannot answer all four
 * is the report this package exists to replace.
 */

const MARKERS = {
  error: 'LOST',
  warning: 'WARN',
  info: 'NOTE',
  notice: 'DIFF',
};

const COLOURS = {
  error: '\u001b[31m',
  warning: '\u001b[33m',
  info: '\u001b[36m',
  notice: '\u001b[90m',
  dim: '\u001b[90m',
  bold: '\u001b[1m',
  reset: '\u001b[0m',
};

const RULE_MARKERS = {
  DUPLICATE_ID: 'DUPLICATE',
  DUPLICATE_ID_IN_SOURCE: 'WARN',
  BLOCK_MOVED: 'MOVED',
  PART_OMITTED: 'PART',
  NEW_IDS: 'NEW',
  CONTENT_CHANGED: 'EDITED',
  DATA_ATTRIBUTE_DROPPED: 'ATTR',
};

export function formatHuman(report, options = {}) {
  const colour = options.colour ? (name, text) => COLOURS[name] + text + COLOURS.reset : (_name, text) => text;
  const lines = [];
  const { counts, summary } = report;

  lines.push(colour('bold', 'block identity check')
    + colour('dim', `  ${report.idAttribute}`));
  lines.push(colour('dim',
    `${counts.beforeBlocks} identified block(s) in, ${counts.afterBlocks} out`
    + `  ·  intact ${counts.intact}  lost ${counts.lost}  duplicated ${counts.duplicated}`
    + `  moved ${counts.moved}  new ${counts.added}`
    + (counts.partsOmitted ? `  parts omitted ${counts.partsOmitted}` : '')));

  const baselined = report.baselined || [];
  if (report.baselineApplied) {
    lines.push(colour('dim',
      `baseline: ${report.baselineApplied.accepted} accepted`
      + `, ${report.baselineApplied.matched} still present here`
      + `, ${report.baselineApplied.stale} stale`));
  }

  if (report.findings.length === 0 && baselined.length === 0) {
    lines.push('');
    lines.push(colour('info', 'clean: every identifier survived the round trip, in order, with its attributes.'));
    return lines.join('\n');
  }

  for (const finding of report.findings) {
    lines.push('');
    lines.push(formatFinding(finding, colour));
  }

  // A baseline takes a finding out of the exit code. It never takes it out of
  // the report: a document that lost an identifier is never described as clean.
  if (baselined.length > 0) {
    lines.push('');
    lines.push(colour('dim', `accepted by the baseline -- still real, still here (${baselined.length}):`));
    for (const finding of baselined) {
      lines.push('');
      lines.push(formatFinding(finding, colour));
    }
  }

  lines.push('');
  if (report.findings.length === 0) {
    lines.push(colour('info', 'no new findings.') + colour('dim', ` ${baselined.length} accepted by the baseline.`));
  } else {
    lines.push(colour('bold', summaryLine(summary))
      + (baselined.length > 0 ? colour('dim', `, ${baselined.length} baselined`) : ''));
  }
  return lines.join('\n');
}

function formatFinding(finding, colour) {
  const marker = finding.baselined
    ? 'BASELINED'
    : (RULE_MARKERS[finding.rule] || MARKERS[finding.severity]);
  const head = [
    colour(finding.baselined ? 'notice' : finding.severity, marker.padEnd(9)),
    colour('bold', finding.rule),
  ];
  const locator = finding.locator;
  if (finding.id) {
    head.push(colour('dim', finding.idRole === 'anchor' ? '· under id' : '· id'), finding.id);
  }
  if (finding.members.length > 0 && finding.idRole === 'anchor') {
    head.push(colour('dim', `· ${finding.members.length} blocks`));
  }

  const lines = [head.join(' ')];
  const indent = '           ';

  if (locator) {
    lines.push(indent + colour('dim', finding.idRole === 'anchor' ? 'from  ' : 'where ')
      + `${locator.tag} · block ${locator.blockIndex} of the before document · line ${locator.line}`);
  }
  if (locator && locator.preview) lines.push(indent + colour('dim', 'text  ') + `"${locator.preview}"`);
  if (locator && locator.path) lines.push(indent + colour('dim', 'at    ') + locator.path);
  lines.push(indent + colour('dim', 'cause ') + wrap(finding.cause, indent.length + 6));

  if (finding.counterpart) {
    const attributes = finding.counterpart.attributes.length > 0
      ? finding.counterpart.attributes.join(' ')
      : 'no attributes';
    lines.push(indent + colour('dim', 'after ')
      + `${finding.counterpart.tag} at line ${finding.counterpart.line} (${attributes})`);
  }

  for (const item of finding.evidence) {
    lines.push(indent + colour('dim', '·     ') + wrap(item, indent.length + 6));
  }

  if (finding.members.length > 0) {
    const shown = finding.members.slice(0, 8);
    for (const member of shown) {
      lines.push(indent + colour('dim', '-     ')
        + `${member.locator.tag} block ${member.locator.blockIndex}, line ${member.locator.line}`
        + `${member.rule ? ` ${member.rule}` : ''} · id ${member.id} · "${member.locator.preview}"`);
    }
    if (finding.members.length > shown.length) {
      lines.push(indent + colour('dim', `-     and ${finding.members.length - shown.length} more`));
    }
  }

  lines.push(indent + colour('dim', `confidence ${finding.confidence}`));
  return lines.join('\n');
}

function wrap(text, indentWidth, width = 96) {
  const limit = Math.max(40, width - indentWidth);
  const words = text.split(' ');
  const lines = [];
  let current = '';
  for (const word of words) {
    if (current.length + word.length + 1 > limit) {
      lines.push(current);
      current = word;
    } else {
      current = current ? `${current} ${word}` : word;
    }
  }
  if (current) lines.push(current);
  return lines.join('\n' + ' '.repeat(indentWidth));
}

function summaryLine(summary) {
  const parts = [];
  if (summary.error) parts.push(`${summary.error} error(s)`);
  if (summary.warning) parts.push(`${summary.warning} warning(s)`);
  if (summary.info) parts.push(`${summary.info} note(s)`);
  if (summary.notice) parts.push(`${summary.notice} edit(s)`);
  return parts.length > 0 ? parts.join(', ') : 'nothing to report';
}

export { summaryLine };
