/**
 * Stats.gs
 * -----------------------------------------------------------------------
 * Very small counters for job outcomes (queued / auto_queued / completed
 * / failed / deduped), stored in Script Properties so they survive
 * across trigger runs. Read via getStats() - shown as a footer line on
 * both the Gmail card and the Drive homepage card (see addStatsFooter
 * in Code.gs), and useful for a status/debug view from the editor too.
 * -----------------------------------------------------------------------
 */

const STATS_KEY = "SUPERDOCS_STATS";

/**
 * Increments a named counter (e.g. "queued", "completed", "failed",
 * "deduped", "auto_queued"). Safe to call with any string - unknown
 * keys just start at 0 and grow.
 */
function recordStat(statName) {
  try {
    const props = PropertiesService.getScriptProperties();
    const raw = props.getProperty(STATS_KEY);
    const stats = raw ? JSON.parse(raw) : {};

    stats[statName] = (stats[statName] || 0) + 1;
    stats._lastUpdated = new Date().toISOString();

    props.setProperty(STATS_KEY, JSON.stringify(stats));
  } catch (err) {
    // Stats are a bonus signal, never allow them to break the actual
    // job flow (upload/export/notify) that calls this.
    console.warn("recordStat: failed to record '" + statName + "': " + err);
  }
}

/**
 * Reads back the current counters. Handy to run manually from the
 * Apps Script editor's "Execution log" while debugging, or to surface
 * in a status card in the add-on UI.
 */
function getStats() {
  const raw = PropertiesService.getScriptProperties().getProperty(STATS_KEY);
  return raw ? JSON.parse(raw) : {};
}

/**
 * Optional: reset all counters (e.g. before a demo run so numbers
 * start clean). Run manually from the Apps Script editor.
 */
function resetStats() {
  PropertiesService.getScriptProperties().deleteProperty(STATS_KEY);
  console.log("Stats reset.");
}
