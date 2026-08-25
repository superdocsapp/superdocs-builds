/**
 * The ServiceNow Table API client.
 *
 * There is one of these, and it speaks HTTP. Whether it is pointed at the mock
 * instance in this process or at a real ServiceNow tenant is a base URL and a
 * credential — nothing else in the app changes, and nothing else in the app is
 * allowed to know which one answered.
 */

import { log } from "../log.js";

const DEFAULT_TIMEOUT_MS = 20_000;
const MAX_RETRIES = 2;

export class ServiceNowError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.name = "ServiceNowError";
    this.status = status;
    this.detail = detail;
  }
}

export class ServiceNowClient {
  constructor({ instanceUrl, username, password, timeoutMs = DEFAULT_TIMEOUT_MS }) {
    this.instanceUrl = String(instanceUrl).replace(/\/+$/u, "");
    this.authorization = `Basic ${Buffer.from(`${username}:${password}`).toString("base64")}`;
    this.timeoutMs = timeoutMs;
  }

  /**
   * `sysparm_display_value=all` returns every field as { value, display_value }.
   * The normalizer needs both — the label for a reference, the raw value for a
   * date — so this is the shape the app always asks for.
   */
  async listTable(table, params = {}) {
    const search = new URLSearchParams({
      sysparm_display_value: "all",
      sysparm_exclude_reference_link: "true",
      ...params
    });

    const { payload, headers } = await this.#request(
      `/api/now/table/${table}?${search.toString()}`
    );

    return {
      rows: payload?.result ?? [],
      total: Number.parseInt(headers.get("x-total-count") ?? "", 10) || (payload?.result?.length ?? 0)
    };
  }

  async getRecord(table, sysId, params = {}) {
    const search = new URLSearchParams({
      sysparm_display_value: "all",
      sysparm_exclude_reference_link: "true",
      ...params
    });

    const { payload } = await this.#request(
      `/api/now/table/${table}/${encodeURIComponent(sysId)}?${search.toString()}`
    );

    return payload?.result ?? null;
  }

  async patchRecord(table, sysId, body) {
    const { payload } = await this.#request(
      `/api/now/table/${table}/${encodeURIComponent(sysId)}?sysparm_display_value=all&sysparm_exclude_reference_link=true`,
      { method: "PATCH", body }
    );

    return payload?.result ?? null;
  }

  async #request(path, { method = "GET", body } = {}) {
    const url = `${this.instanceUrl}${path}`;
    let lastError;

    for (let attempt = 0; attempt <= MAX_RETRIES; attempt += 1) {
      try {
        const response = await fetch(url, {
          method,
          headers: {
            Accept: "application/json",
            Authorization: this.authorization,
            ...(body ? { "Content-Type": "application/json" } : {})
          },
          body: body ? JSON.stringify(body) : undefined,
          signal: AbortSignal.timeout(this.timeoutMs)
        });

        const text = await response.text();
        const payload = text ? safeJson(text) : null;

        if (!response.ok) {
          const retryable = response.status === 429 || response.status >= 500;

          if (retryable && attempt < MAX_RETRIES) {
            log.warn("servicenow request retrying", { status: response.status, path, attempt });
            await sleep(300 * 2 ** attempt);
            continue;
          }

          throw new ServiceNowError(
            payload?.error?.message ?? `ServiceNow ${method} ${path} failed with ${response.status}`,
            response.status,
            payload?.error?.detail ?? text.slice(0, 300)
          );
        }

        return { payload, headers: response.headers };
      } catch (error) {
        lastError = error;
        if (error instanceof ServiceNowError || attempt >= MAX_RETRIES) throw error;
        log.warn("servicenow request failed, retrying", {
          path,
          attempt,
          detail: String(error.message ?? error)
        });
        await sleep(300 * 2 ** attempt);
      }
    }

    throw lastError ?? new ServiceNowError("ServiceNow request failed.", 0, null);
  }
}

function safeJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
