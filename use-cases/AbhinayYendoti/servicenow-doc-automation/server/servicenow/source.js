/**
 * ServiceNow source adapter.
 *
 * Everything downstream consumes the normalized ChangeRequest below, never a raw
 * ServiceNow row. That is the seam that lets the mock instance be swapped for a
 * real tenant without touching document generation, verification or SuperDocs.
 *
 * There is only one implementation now, and that is the point: `mock` and `live`
 * are the same class over the same HTTP client, differing only in which base URL
 * and credentials `config.js` handed it. The mock is a real Table API served by
 * this process (see `mockApi.js`), so both modes exercise identical code.
 */

import { ServiceNowClient } from "./client.js";

/** ServiceNow `change_request.state` values, keyed by the stored code. */
const STATE_LABELS = {
  "-5": "New",
  "-4": "Assess",
  "-3": "Authorize",
  "-2": "Scheduled",
  "-1": "Implement",
  "0": "Review",
  "3": "Closed",
  "4": "Canceled"
};

/**
 * @typedef {object} ChangeRequest
 * @property {string} id           ServiceNow sys_id
 * @property {string} number
 * @property {string} short_description
 * @property {string} configuration_item
 * @property {string} work_notes
 * @property {string} resolution_code
 * @property {string} status
 * @property {string} requester
 * @property {string} assignment_group
 * @property {string} risk
 * @property {string|null} planned_start ISO-8601
 * @property {string|null} planned_end   ISO-8601
 */

/**
 * Raw ServiceNow row -> canonical ChangeRequest. The only place field names are
 * translated.
 *
 * Under `sysparm_display_value=all` every field arrives as
 * { value, display_value }, and which half is wanted depends on the field:
 * a reference is only useful as its display value, but a datetime's display
 * value is the caller's locale format ("08/18/2026 22:00:00") and only `value`
 * is the parseable "YYYY-MM-DD HH:MM:SS". Reading the wrong half is how a date
 * silently becomes null against a real instance.
 */
export function normalizeChangeRow(row) {
  return {
    id: raw(row.sys_id),
    number: raw(row.number),
    short_description: raw(row.short_description),
    configuration_item: reference(row.cmdb_ci),
    work_notes: raw(row.work_notes),
    resolution_code: raw(row.close_code),
    status: state(row.state),
    requester: reference(row.requested_by),
    assignment_group: reference(row.assignment_group),
    risk: raw(row.risk),
    planned_start: toIso(raw(row.start_date)),
    planned_end: toIso(raw(row.end_date))
  };
}

export class ServiceNowSource {
  /**
   * @param {object} options
   * @param {"mock"|"live"} options.mode  reported to the UI; does not change behaviour
   * @param {ServiceNowClient} options.client
   */
  constructor({ mode, client }) {
    this.mode = mode;
    this.client = client;
  }

  get kind() {
    return this.mode;
  }

  /** Closed changes, most recently updated first — the reviewer's work queue. */
  async listChanges({ limit = 25 } = {}) {
    const { rows } = await this.client.listTable("change_request", {
      sysparm_query: "state=3^ORDERBYDESCsys_updated_on",
      sysparm_limit: String(limit)
    });

    return rows.map(normalizeChangeRow);
  }

  async getChange(number) {
    const { rows } = await this.client.listTable("change_request", {
      sysparm_query: `number=${number}`,
      sysparm_limit: "1"
    });

    return rows.length ? normalizeChangeRow(rows[0]) : null;
  }

  /**
   * Record the exported document against the change. ServiceNow journal fields
   * append rather than overwrite, so this adds a note; it never edits history.
   */
  async recordDocument(sysId, note) {
    const row = await this.client.patchRecord("change_request", sysId, { work_notes: note });
    return row ? normalizeChangeRow(row) : null;
  }
}

export function createChangeSource(config) {
  const { mode, instanceUrl, username, password } = config.serviceNow;
  return new ServiceNowSource({
    mode,
    client: new ServiceNowClient({ instanceUrl, username, password })
  });
}

/**
 * A field's stored value. Handles the three shapes a ServiceNow field can take:
 * absent, a plain scalar, or { value, display_value }.
 */
function raw(field) {
  if (field === null || field === undefined) return "";
  if (typeof field === "object") return String(field.value ?? field.display_value ?? "").trim();
  return String(field).trim();
}

/** A reference field is only meaningful as its display value. */
function reference(field) {
  if (field === null || field === undefined) return "";
  if (typeof field === "object") return String(field.display_value ?? field.value ?? "").trim();
  return String(field).trim();
}

/**
 * `state` is a choice field: the stored value is a code, the display value is
 * already the label. Prefer resolving the code, and fall back to whatever the
 * instance called it.
 */
function state(field) {
  const code = raw(field);
  if (STATE_LABELS[code]) return STATE_LABELS[code];

  const label = reference(field);
  return label || code;
}

/** ServiceNow stores datetimes as "YYYY-MM-DD HH:MM:SS" in UTC. */
function toIso(value) {
  if (!value) return null;
  const parsed = new Date(value.replace(" ", "T") + (value.includes("Z") ? "" : "Z"));
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
}
