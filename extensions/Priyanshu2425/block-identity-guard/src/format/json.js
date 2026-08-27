/**
 * The machine report. Stable enough to diff between runs and to store as a
 * baseline: no timestamps, no paths, no ordering that depends on a hash table.
 */

export function formatJson(report, options = {}) {
  return JSON.stringify(report, null, options.compact ? 0 : 2);
}
