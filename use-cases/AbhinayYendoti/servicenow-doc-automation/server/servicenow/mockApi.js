/**
 * A mock ServiceNow instance, served as a real Table API.
 *
 * This is not a fixture array handed straight to the app. It is an HTTP surface
 * mounted inside this process that behaves the way `/api/now/table/{table}`
 * behaves on a real instance: basic auth, encoded queries, `sysparm_*`
 * parameters, ServiceNow-shaped error bodies, pagination headers, and PATCH
 * write-back.
 *
 * That matters because the app has exactly one ServiceNow client
 * (`client.js`), and it speaks HTTP. Pointing it at this router or at a real
 * instance exercises the same code path — parsing, auth, pagination, retries,
 * error handling and all — so "swap the mock for a live instance" is a base URL
 * change rather than a rewrite, and the mock cannot quietly be more forgiving
 * than the real thing.
 *
 * Latency and failure injection are configurable so the UI's loading and error
 * states are exercised by something real rather than assumed.
 */

import express from "express";

import { STATE_CODES, changeRequestRows, referenceTables } from "./fixtures.js";

/** Which table a reference field points at, so a sys_id resolves to a label. */
const REFERENCE_FIELDS = {
  cmdb_ci: "cmdb_ci",
  requested_by: "sys_user",
  assignment_group: "sys_user_group"
};

/** Choice fields carry a code as the value and a label as the display value. */
const CHOICE_FIELDS = { state: STATE_CODES };

const DATE_FIELDS = new Set(["start_date", "end_date", "sys_created_on", "sys_updated_on"]);

const TABLES = new Set(["change_request"]);

/**
 * Operators are matched longest-first: `ISNOTEMPTY` has to win over `IN`, and
 * `>=` over `>`, or a query silently parses into the wrong condition.
 */
const OPERATORS = [
  ["ISNOTEMPTY", (value) => String(value ?? "").trim() !== ""],
  ["ISEMPTY", (value) => String(value ?? "").trim() === ""],
  ["STARTSWITH", (value, operand) => lower(value).startsWith(lower(operand))],
  ["ENDSWITH", (value, operand) => lower(value).endsWith(lower(operand))],
  ["NOTLIKE", (value, operand) => !lower(value).includes(lower(operand))],
  ["LIKE", (value, operand) => lower(value).includes(lower(operand))],
  ["NOTIN", (value, operand) => !operand.split(",").map(lower).includes(lower(value))],
  ["IN", (value, operand) => operand.split(",").map(lower).includes(lower(value))],
  [">=", (value, operand) => String(value) >= operand],
  ["<=", (value, operand) => String(value) <= operand],
  ["!=", (value, operand) => String(value ?? "") !== operand],
  [">", (value, operand) => String(value) > operand],
  ["<", (value, operand) => String(value) < operand],
  ["=", (value, operand) => String(value ?? "") === operand]
];

function lower(value) {
  return String(value ?? "").toLowerCase();
}

class ServiceNowFault extends Error {
  constructor(status, message, detail) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

/**
 * ServiceNow encoded query -> conditions plus ordering.
 *
 * Terms are separated by `^` and AND-ed. A term prefixed `OR` joins the
 * previous term as an alternative, which is why conditions come back as groups:
 * every group must match, and a group matches if any of its terms does.
 */
export function parseEncodedQuery(query) {
  const groups = [];
  const order = [];

  for (const rawTerm of String(query ?? "").split("^")) {
    const term = rawTerm.trim();
    if (!term) continue;

    if (/^ORDERBYDESC/iu.test(term)) {
      order.push({ field: term.slice("ORDERBYDESC".length), direction: "desc" });
      continue;
    }

    if (/^ORDERBY/iu.test(term)) {
      order.push({ field: term.slice("ORDERBY".length), direction: "asc" });
      continue;
    }

    const isOr = /^OR/u.test(term) && groups.length > 0 && parseCondition(term.slice(2));
    const condition = parseCondition(isOr ? term.slice(2) : term);

    if (!condition) {
      throw new ServiceNowFault(400, "Invalid query", `Could not parse query term "${term}".`);
    }

    if (isOr) groups[groups.length - 1].push(condition);
    else groups.push([condition]);
  }

  return { groups, order };
}

function parseCondition(term) {
  for (const [token, test] of OPERATORS) {
    const index = term.indexOf(token);
    if (index <= 0) continue;

    const field = term.slice(0, index).trim();
    const operand = term.slice(index + token.length).trim();
    if (!field) continue;

    return { field, token, operand, test };
  }

  return null;
}

function matches(row, groups) {
  return groups.every((group) =>
    group.some((condition) => condition.test(row[condition.field], condition.operand))
  );
}

function sortRows(rows, order) {
  if (!order.length) return rows;

  return [...rows].sort((left, right) => {
    for (const { field, direction } of order) {
      const a = String(left[field] ?? "");
      const b = String(right[field] ?? "");
      if (a === b) continue;
      return direction === "desc" ? (a < b ? 1 : -1) : a > b ? 1 : -1;
    }
    return 0;
  });
}

/** ServiceNow renders datetimes in the caller's display format, not ISO. */
function displayDate(value) {
  const raw = String(value ?? "").trim();
  if (!raw) return "";

  const [date, time = ""] = raw.split(" ");
  const [year, month, day] = date.split("-");
  if (!year || !month || !day) return raw;

  return `${month}/${day}/${year}${time ? ` ${time}` : ""}`;
}

function displayValueOf(field, value) {
  if (REFERENCE_FIELDS[field]) {
    return referenceTables[REFERENCE_FIELDS[field]]?.[value] ?? "";
  }
  if (CHOICE_FIELDS[field]) return CHOICE_FIELDS[field][String(value)] ?? String(value ?? "");
  if (DATE_FIELDS.has(field)) return displayDate(value);
  return String(value ?? "");
}

/**
 * Shape a stored row the way `sysparm_display_value` asks for.
 *
 *   "all"   every field as { value, display_value } — and reference fields get
 *           a `link`, unless the caller excluded reference links
 *   "true"  display values only
 *   "false" raw stored values (the default)
 */
export function projectRow(row, { displayValue, fields, excludeReferenceLink, instanceUrl }) {
  const chosen = fields.length ? fields : Object.keys(row);
  const output = {};

  for (const field of chosen) {
    if (!(field in row)) continue;
    const value = row[field];

    if (displayValue === "all") {
      const entry = { value: String(value ?? ""), display_value: displayValueOf(field, value) };

      if (REFERENCE_FIELDS[field] && !excludeReferenceLink && value) {
        entry.link = `${instanceUrl}/api/now/table/${REFERENCE_FIELDS[field]}/${value}`;
      }

      output[field] = entry;
      continue;
    }

    output[field] = displayValue === "true" ? displayValueOf(field, value) : String(value ?? "");
  }

  return output;
}

function unauthorized(response) {
  response
    .status(401)
    .set("WWW-Authenticate", 'Basic realm="ServiceNow"')
    .json({
      error: {
        message: "User Not Authenticated",
        detail: "Required to provide Auth information"
      },
      status: "failure"
    });
}

/**
 * @param {object} options
 * @param {string} options.username   credentials the mock instance accepts
 * @param {string} options.password
 * @param {number} [options.latencyMs]    simulated round-trip time
 * @param {number} [options.failureRate]  0-1, share of reads that fail with 503
 * @param {string} [options.instanceUrl]  used to build reference links
 */
export function createMockServiceNowApi({
  username,
  password,
  latencyMs = 0,
  failureRate = 0,
  instanceUrl = "http://127.0.0.1:8787/mock/servicenow",
  rows = changeRequestRows
} = {}) {
  // Cloned so a PATCH mutates this instance's copy, not the imported module.
  const table = new Map(rows.map((row) => [row.sys_id, { ...row }]));
  const expected = `Basic ${Buffer.from(`${username}:${password}`).toString("base64")}`;

  const router = express.Router();
  router.use(express.json({ limit: "256kb" }));

  router.use(async (request, response, next) => {
    if (latencyMs > 0) await new Promise((resolve) => setTimeout(resolve, latencyMs));

    if (request.get("authorization") !== expected) {
      unauthorized(response);
      return;
    }

    if (failureRate > 0 && Math.random() < failureRate) {
      response.status(503).json({
        error: { message: "Service temporarily unavailable", detail: "Injected fault" },
        status: "failure"
      });
      return;
    }

    next();
  });

  router.use("/api/now/table/:table", (request, response, next) => {
    if (!TABLES.has(request.params.table)) {
      response.status(400).json({
        error: {
          message: "Invalid table",
          detail: `Table ${request.params.table} does not exist on this instance.`
        },
        status: "failure"
      });
      return;
    }
    next();
  });

  router.get("/api/now/table/change_request", (request, response) => {
    const query = request.query;

    let parsed;
    try {
      parsed = parseEncodedQuery(query.sysparm_query);
    } catch (fault) {
      response
        .status(fault.status)
        .json({ error: { message: fault.message, detail: fault.detail }, status: "failure" });
      return;
    }

    const all = sortRows([...table.values()].filter((row) => matches(row, parsed.groups)), parsed.order);

    const limit = clampInt(query.sysparm_limit, 1, 1000, 100);
    const offset = clampInt(query.sysparm_offset, 0, Number.MAX_SAFE_INTEGER, 0);
    const page = all.slice(offset, offset + limit);

    const options = readProjection(query, instanceUrl);

    response
      .set("X-Total-Count", String(all.length))
      .json({ result: page.map((row) => projectRow(row, options)) });
  });

  router.get("/api/now/table/change_request/:sysId", (request, response) => {
    const row = table.get(request.params.sysId);

    if (!row) {
      notFound(response, request.params.sysId);
      return;
    }

    response.json({ result: projectRow(row, readProjection(request.query, instanceUrl)) });
  });

  /**
   * Write-back. The workflow uses this to record the exported document against
   * the change, which is the same call it would make on a real instance.
   */
  router.patch("/api/now/table/change_request/:sysId", (request, response) => {
    const row = table.get(request.params.sysId);

    if (!row) {
      notFound(response, request.params.sysId);
      return;
    }

    const body = request.body ?? {};
    const writable = ["work_notes", "close_notes", "u_document_reference", "comments"];
    const rejected = Object.keys(body).filter((field) => !writable.includes(field));

    if (rejected.length) {
      response.status(403).json({
        error: {
          message: "Operation Forbidden",
          detail: `Field(s) not writable by this account: ${rejected.join(", ")}.`
        },
        status: "failure"
      });
      return;
    }

    // ServiceNow journal fields append; they do not overwrite.
    for (const field of writable) {
      if (typeof body[field] !== "string" || !body[field]) continue;
      row[field] = field === "work_notes" && row.work_notes
        ? `${row.work_notes}\n\n${body[field]}`
        : body[field];
    }

    row.sys_updated_on = new Date().toISOString().replace("T", " ").slice(0, 19);

    response.json({ result: projectRow(row, readProjection(request.query, instanceUrl)) });
  });

  router.get("/api/now/stats/change_request", (_request, response) => {
    const counts = {};
    for (const row of table.values()) {
      const label = STATE_CODES[row.state] ?? row.state;
      counts[label] = (counts[label] ?? 0) + 1;
    }
    response.json({ result: { stats: { count: table.size, by_state: counts } } });
  });

  return router;
}

function readProjection(query, instanceUrl) {
  return {
    displayValue: String(query.sysparm_display_value ?? "false"),
    fields: String(query.sysparm_fields ?? "")
      .split(",")
      .map((field) => field.trim())
      .filter(Boolean),
    excludeReferenceLink: String(query.sysparm_exclude_reference_link ?? "false") === "true",
    instanceUrl
  };
}

function notFound(response, sysId) {
  response.status(404).json({
    error: { message: "No Record found", detail: `Record ${sysId} not found in change_request.` },
    status: "failure"
  });
}

function clampInt(value, min, max, fallback) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, parsed));
}
