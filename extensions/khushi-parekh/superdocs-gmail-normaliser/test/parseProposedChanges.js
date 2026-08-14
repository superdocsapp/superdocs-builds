/**
 * Node-testable copy of SuperDocsClient.gs -> parseProposedChanges().
 *
 * WHY THIS IS DUPLICATED, NOT SHARED (logged assumption, see README):
 * Apps Script's V8 runtime does not support CommonJS (require/module),
 * so the .gs source cannot be require()'d directly from Node without a
 * bundler step. Rather than add build tooling for one function, this
 * project keeps a byte-for-byte copy here purely so the core parsing
 * logic - the single most common integration bug per the task doc - can
 * be verified with zero installs and no live SuperDocs key. If this
 * function ever changes in SuperDocsClient.gs, update it here too.
 */
function parseProposedChanges(raw) {
  if (raw == null) return [];
  if (Array.isArray(raw)) return raw;
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      return [];
    }
  }
  return [];
}

module.exports = { parseProposedChanges };
