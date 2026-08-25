import express from "express";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { ServiceNowClient, ServiceNowError } from "./client.js";
import { createMockServiceNowApi, parseEncodedQuery, projectRow } from "./mockApi.js";
import { ServiceNowSource, normalizeChangeRow } from "./source.js";

const CREDENTIALS = { username: "svcflow.test", password: "test-secret" };

describe("normalizeChangeRow", () => {
  /** The shape a real instance returns under sysparm_display_value=all. */
  const row = {
    sys_id: { value: "8f4d1b2c9a7e4d3f8b21c05e6a1d4471", display_value: "8f4d1b2c9a7e4d3f8b21c05e6a1d4471" },
    number: { value: "CHG0010042", display_value: "CHG0010042" },
    short_description: { value: "Upgrade production API gateway", display_value: "Upgrade production API gateway" },
    cmdb_ci: { value: "3a1f77c2b1d54e0a", display_value: "PROD-API-GATEWAY-01" },
    work_notes: { value: "Maintenance window completed.", display_value: "Maintenance window completed." },
    close_code: { value: "Successful", display_value: "Successful" },
    state: { value: "3", display_value: "Closed" },
    requested_by: { value: "a11c2e93", display_value: "Asha Rao" },
    assignment_group: { value: "d81f0b44", display_value: "Platform Engineering" },
    start_date: { value: "2026-08-18 22:00:00", display_value: "08/18/2026 22:00:00" },
    end_date: { value: "2026-08-18 23:00:00", display_value: "08/18/2026 23:00:00" },
    risk: { value: "Moderate", display_value: "Moderate" }
  };

  it("resolves reference fields to their display value", () => {
    const change = normalizeChangeRow(row);
    expect(change.configuration_item).toBe("PROD-API-GATEWAY-01");
    expect(change.requester).toBe("Asha Rao");
  });

  it("translates ServiceNow state codes to labels", () => {
    expect(normalizeChangeRow(row).status).toBe("Closed");
    expect(normalizeChangeRow({ ...row, state: { value: "-1", display_value: "Implement" } }).status).toBe(
      "Implement"
    );
  });

  /**
   * The regression this guards: a datetime's display_value is the caller's
   * locale format, which Date cannot parse. Reading it instead of `value`
   * turns every maintenance window into null against a real instance.
   */
  it("reads datetimes from the stored value, not the localised display value", () => {
    expect(normalizeChangeRow(row).planned_start).toBe("2026-08-18T22:00:00.000Z");
  });

  it("keeps missing values as empty strings rather than undefined", () => {
    const change = normalizeChangeRow({ ...row, close_code: "", cmdb_ci: null });
    expect(change.resolution_code).toBe("");
    expect(change.configuration_item).toBe("");
  });

  it("tolerates plain-string fields", () => {
    expect(normalizeChangeRow({ ...row, cmdb_ci: "PROD-API-GATEWAY-01" }).configuration_item).toBe(
      "PROD-API-GATEWAY-01"
    );
  });
});

describe("parseEncodedQuery", () => {
  it("splits conditions on ^ and reads ordering", () => {
    const { groups, order } = parseEncodedQuery("state=3^ORDERBYDESCsys_updated_on");
    expect(groups).toHaveLength(1);
    expect(order).toEqual([{ field: "sys_updated_on", direction: "desc" }]);
  });

  it("groups ^OR terms as alternatives of the preceding condition", () => {
    const { groups } = parseEncodedQuery("state=3^ORstate=4^risk=High");
    expect(groups.map((group) => group.length)).toEqual([2, 1]);
  });

  it("prefers the longer operator token", () => {
    expect(parseEncodedQuery("work_notes ISNOTEMPTY").groups[0][0].token).toBe("ISNOTEMPTY");
    expect(parseEncodedQuery("number LIKE CHG001").groups[0][0].token).toBe("LIKE");
  });

  it("rejects a term it cannot parse", () => {
    expect(() => parseEncodedQuery("garbage")).toThrow(/Invalid query/u);
    expect(() => parseEncodedQuery("garbage")).toThrow(
      expect.objectContaining({ status: 400 })
    );
  });
});

describe("projectRow", () => {
  const stored = { sys_id: "abc", cmdb_ci: "3a1f77c2b1d54e0a", state: "3", start_date: "2026-08-18 22:00:00" };

  it("returns { value, display_value } pairs for sysparm_display_value=all", () => {
    const projected = projectRow(stored, {
      displayValue: "all",
      fields: [],
      excludeReferenceLink: true,
      instanceUrl: "http://x"
    });

    expect(projected.cmdb_ci).toEqual({ value: "3a1f77c2b1d54e0a", display_value: "PROD-API-GATEWAY-01" });
    expect(projected.state.display_value).toBe("Closed");
    expect(projected.start_date.display_value).toBe("08/18/2026 22:00:00");
  });

  it("honours sysparm_fields", () => {
    const projected = projectRow(stored, {
      displayValue: "false",
      fields: ["sys_id", "state"],
      excludeReferenceLink: true,
      instanceUrl: "http://x"
    });

    expect(Object.keys(projected)).toEqual(["sys_id", "state"]);
  });
});

/**
 * The source is exercised over real HTTP against the mock instance, because
 * that is how it runs in production. Query parsing, auth, projection and
 * normalization all participate.
 */
describe("ServiceNowSource over the mock Table API", () => {
  let server;
  let source;
  let baseUrl;

  beforeAll(async () => {
    const app = express();
    app.use("/mock/servicenow", createMockServiceNowApi({ ...CREDENTIALS }));

    server = await new Promise((resolve) => {
      const listener = app.listen(0, "127.0.0.1", () => resolve(listener));
    });

    baseUrl = `http://127.0.0.1:${server.address().port}/mock/servicenow`;
    source = new ServiceNowSource({
      mode: "mock",
      client: new ServiceNowClient({ instanceUrl: baseUrl, ...CREDENTIALS })
    });
  });

  afterAll(() => new Promise((resolve) => server.close(resolve)));

  it("returns normalized changes, never raw ServiceNow rows", async () => {
    const [change] = await source.listChanges();
    expect(change.configuration_item).toMatch(/^[A-Z]/u);
    expect(change).not.toHaveProperty("cmdb_ci");
  });

  it("applies the state=3 filter server-side", async () => {
    const changes = await source.listChanges();
    expect(changes.every((change) => change.status === "Closed")).toBe(true);
    expect(changes.some((change) => change.number === "CHG0010055")).toBe(false);
  });

  it("orders the queue by most recently updated", async () => {
    const changes = await source.listChanges();
    expect(changes[0].number).toBe("CHG0010054");
  });

  it("looks a change up by number", async () => {
    expect(await source.getChange("CHG0010042")).not.toBeNull();
    expect(await source.getChange("CHG9999999")).toBeNull();
  });

  it("parses dates through the full HTTP path", async () => {
    const change = await source.getChange("CHG0010042");
    expect(change.planned_start).toBe("2026-08-18T22:00:00.000Z");
  });

  it("appends a work note on write-back rather than overwriting it", async () => {
    const before = await source.getChange("CHG0010045");
    const after = await source.recordDocument(before.id, "Document exported.");

    expect(after.work_notes.startsWith(before.work_notes)).toBe(true);
    expect(after.work_notes).toContain("Document exported.");
  });

  it("rejects bad credentials with a ServiceNow 401", async () => {
    const wrong = new ServiceNowSource({
      mode: "mock",
      client: new ServiceNowClient({ instanceUrl: baseUrl, username: "nobody", password: "wrong" })
    });

    await expect(wrong.listChanges()).rejects.toThrow(ServiceNowError);
  });

  it("refuses to write a field the account does not own", async () => {
    const client = new ServiceNowClient({ instanceUrl: baseUrl, ...CREDENTIALS });
    const failure = await client
      .patchRecord("change_request", "8f4d1b2c9a7e4d3f8b21c05e6a1d4471", { close_code: "Failed" })
      .catch((error) => error);

    expect(failure).toBeInstanceOf(ServiceNowError);
    expect(failure.status).toBe(403);
    expect(failure.detail).toMatch(/not writable/u);
  });
});
