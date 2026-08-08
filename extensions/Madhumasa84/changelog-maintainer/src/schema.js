import { ChangelogError } from './errors.js';

const RELEASE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const ITEM_ID = RELEASE_ID;
const CATEGORIES = new Set(['Added', 'Changed', 'Fixed', 'Deprecated', 'Removed']);
const UNSAFE = /(\u001b|X-Amz-Signature|Authorization:\s*Bearer|BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY|<script\b|ignore all previous instructions|system prompt|do not append|execute command)/i;

function string(value, field, max) {
  if (typeof value !== 'string' || value.length === 0 || value.length > max || value.includes('\u0000') || UNSAFE.test(value)) {
    throw new ChangelogError(`invalid or unsafe ${field}`);
  }
  return value;
}

export function validateRelease(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new ChangelogError('release input must be an object');
  for (const key of Object.keys(input)) if (!new Set(['release_id', 'title', 'date', 'items', 'metadata']).has(key)) throw new ChangelogError(`unknown release field: ${key}`);
  const releaseId = string(input.release_id, 'release_id', 64);
  if (!RELEASE_ID.test(releaseId)) throw new ChangelogError('release_id has invalid characters');
  const title = string(input.title, 'title', 160);
  const date = string(input.date, 'date', 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) throw new ChangelogError('date must be YYYY-MM-DD');
  if (!Array.isArray(input.items) || input.items.length === 0) throw new ChangelogError('items must be a non-empty array');
  const ids = new Set();
  const items = input.items.map((item, index) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) throw new ChangelogError(`item ${index + 1} is not an object`);
    for (const key of Object.keys(item)) if (!new Set(['id', 'category', 'title', 'body']).has(key)) throw new ChangelogError(`unknown item field: ${key}`);
    const id = string(item.id, `items[${index}].id`, 64);
    if (!ITEM_ID.test(id)) throw new ChangelogError(`item ${id} has invalid characters`);
    if (ids.has(id)) throw new ChangelogError(`duplicate item id: ${id}`);
    ids.add(id);
    const category = string(item.category, `items[${index}].category`, 32);
    if (!CATEGORIES.has(category)) throw new ChangelogError(`unsupported category: ${category}`);
    return { id, category, title: string(item.title, `items[${index}].title`, 160), body: string(item.body, `items[${index}].body`, 2000) };
  });
  if (input.metadata?.origin === 'superdocs-changelog-maintainer' || input.metadata?.generated_by === 'superdocs-changelog-maintainer') {
    throw new ChangelogError('release input is a generated changelog artifact; self-trigger refused', 'SELF_TRIGGER', 11);
  }
  return { release_id: releaseId, title, date, items, metadata: input.metadata && typeof input.metadata === 'object' ? input.metadata : {} };
}

export function validateManifest(manifest) {
  const statuses = new Set(['awaiting_decisions', 'previewed', 'decisions_recorded', 'append_started', 'appended', 'export_started', 'completed', 'completed_no_change']);
  if (!manifest || manifest.version !== 1 || typeof manifest.run_id !== 'string' || typeof manifest.release_id !== 'string' || !statuses.has(manifest.status)) {
    throw new ChangelogError('manifest is corrupt or unsupported', 'CORRUPT_STATE', 11);
  }
  if (!manifest.candidate_block_sha256 || !manifest.historical_prefix_sha256 || !manifest.input_sha256 || !manifest.expected_canonical_sha256 || typeof manifest.candidate_block !== 'string') {
    throw new ChangelogError('manifest is missing required hashes or candidate content', 'CORRUPT_STATE', 11);
  }
  if (!manifest.release || !Array.isArray(manifest.release.items) || !manifest.decisions || typeof manifest.decisions !== 'object' || Array.isArray(manifest.decisions) || !Array.isArray(manifest.checkpoints) || typeof manifest.canonical_path !== 'string' || typeof manifest.release_path !== 'string' || typeof manifest.state_dir !== 'string' || !manifest.output_hashes || typeof manifest.output_hashes !== 'object' || Array.isArray(manifest.output_hashes)) {
    throw new ChangelogError('manifest has invalid durable state fields', 'CORRUPT_STATE', 11);
  }
  if (manifest.approved_block !== undefined && (typeof manifest.approved_block !== 'string' || typeof manifest.approved_block_sha256 !== 'string')) {
    throw new ChangelogError('manifest has invalid approved content binding', 'CORRUPT_STATE', 11);
  }
  try { validateRelease(manifest.release); } catch { throw new ChangelogError('manifest contains an invalid release input', 'CORRUPT_STATE', 11); }
  return manifest;
}
