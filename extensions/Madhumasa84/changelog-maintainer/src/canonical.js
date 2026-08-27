import { readFile } from 'node:fs/promises';
import { ChangelogError } from './errors.js';

const START = /<!-- changelog:release-id=([A-Za-z0-9][A-Za-z0-9._-]{0,63}) -->/g;
const END = '<!-- changelog:release-end -->';

export function parseCanonical(bytes) {
  let text;
  try { text = new TextDecoder('utf-8', { fatal: true }).decode(bytes); } catch { throw new ChangelogError('canonical changelog is not valid UTF-8'); }
  if (!text.startsWith('# Changelog')) throw new ChangelogError('canonical changelog must begin with # Changelog');
  const releases = [];
  const seen = new Set();
  let match;
  START.lastIndex = 0;
  while ((match = START.exec(text))) {
    const id = match[1];
    if (seen.has(id)) throw new ChangelogError(`duplicate release id in canonical changelog: ${id}`);
    seen.add(id);
    const end = text.indexOf(END, START.lastIndex);
    if (end < 0) throw new ChangelogError(`release ${id} has no end marker`);
    const endExclusive = end + END.length;
    releases.push({ id, startText: match.index, endText: endExclusive, block: text.slice(match.index, endExclusive) });
    START.lastIndex = endExclusive;
  }
  if (text.includes('<!-- changelog:release-id=') && releases.length === 0) throw new ChangelogError('canonical release markers are malformed');
  const byteOffset = (textOffset) => Buffer.byteLength(text.slice(0, textOffset), 'utf8');
  return { text, bytes, releases: releases.map((item) => ({ ...item, startByte: byteOffset(item.startText), endByte: byteOffset(item.endText) })) };
}

export async function readCanonical(path) {
  return parseCanonical(await readFile(path));
}

export function inferHouseStyle(parsed) {
  const latest = parsed.releases.at(-1);
  if (!latest) return { heading: '##', category: '###', item: '- **Title.** Body', version: 1 };
  const heading = latest.block.split(/\r?\n/).find((line) => /^##\s/.test(line));
  const item = latest.block.split(/\r?\n/).find((line) => /^-\s+\*\*/.test(line));
  if (!heading || !item) throw new ChangelogError('unable to infer established changelog house style');
  return { heading: '##', category: '###', item: '- **Title.** Body', version: 1 };
}

function markdownLine(value) {
  return value.replace(/\r?\n/g, ' ').trim();
}

export function buildReleaseBlock(release, style, selected = release.items) {
  const lines = [`<!-- changelog:release-id=${release.release_id} -->`, `${style.heading} ${markdownLine(release.title)} (${release.date})`];
  let category;
  for (const item of selected) {
    if (item.category !== category) {
      category = item.category;
      lines.push('', `${style.category} ${category}`);
    }
    lines.push(`- **${markdownLine(item.title)}.** ${markdownLine(item.body)}`);
  }
  lines.push('', END, '');
  return lines.join('\n');
}

export function itemKey(releaseId, itemId) {
  return `change_${releaseId}_${itemId}`;
}
