import type { Client } from "../domain/clients.js";
import { currentVersion, latestClientVersion, type VersionStore } from "./registry.js";

export type ConsentCellStatus =
  | "CURRENT_CONSENTED"
  | "CURRENT_PENDING_CONSENT"
  | "BEHIND"
  | "BEHIND_NOT_CONSENTED"
  | "NOT_ISSUED";

export interface ConsentCell {
  template_id: string;
  version: string | null;
  current_version: string | null;
  status: ConsentCellStatus;
  consented_on: string | null;
  consent_evidence: string | null;
}

export interface ConsentMatrixRow {
  client_id: string;
  client_name: string;
  cells: ConsentCell[];
}

export interface ConsentMatrix {
  generated_at: string;
  templates: string[];
  rows: ConsentMatrixRow[];
}

/**
 * Clients down, templates across. Every client in the roster gets a row —
 * even one that was never issued anything, which is its own honest cell
 * (NOT_ISSUED), not an omission.
 */
export function buildConsentMatrix(store: VersionStore, clients: Client[]): ConsentMatrix {
  const templateIds = Array.from(new Set(store.template_versions.map((t) => t.template_id))).sort();

  const rows: ConsentMatrixRow[] = clients.map((client) => {
    const cells: ConsentCell[] = templateIds.map((templateId) => {
      const current = currentVersion(store, templateId);
      const latest = latestClientVersion(store, client.id, templateId);

      if (!latest) {
        return {
          template_id: templateId,
          version: null,
          current_version: current?.version ?? null,
          status: "NOT_ISSUED",
          consented_on: null,
          consent_evidence: null,
        };
      }

      const isCurrent = current !== null && latest.version === current.version;
      const consented = latest.consented_on !== null;

      let status: ConsentCellStatus;
      if (isCurrent && consented) status = "CURRENT_CONSENTED";
      else if (isCurrent && !consented) status = "CURRENT_PENDING_CONSENT";
      else if (!isCurrent && consented) status = "BEHIND";
      else status = "BEHIND_NOT_CONSENTED";

      return {
        template_id: templateId,
        version: latest.version,
        current_version: current?.version ?? null,
        status,
        consented_on: latest.consented_on,
        consent_evidence: latest.consent_evidence,
      };
    });

    return { client_id: client.id, client_name: client.name, cells };
  });

  return { generated_at: new Date().toISOString(), templates: templateIds, rows };
}

function cellLabel(cell: ConsentCell): string {
  const v = cell.version ?? "?";
  switch (cell.status) {
    case "NOT_ISSUED":
      return "NOT ISSUED";
    case "CURRENT_CONSENTED":
      return `${v} — current, consented ${cell.consented_on}`;
    case "CURRENT_PENDING_CONSENT":
      return `${v} — current, PENDING CONSENT`;
    case "BEHIND":
      return `${v} — BEHIND (current: ${cell.current_version}), consented ${cell.consented_on}`;
    case "BEHIND_NOT_CONSENTED":
      return `${v} — BEHIND (current: ${cell.current_version}), NOT CONSENTED`;
  }
}

export function formatConsentMatrixTable(matrix: ConsentMatrix): string {
  if (matrix.templates.length === 0) {
    return "(no template versions registered yet)";
  }

  const header = ["Client", ...matrix.templates];
  const rows = matrix.rows.map((row) => [
    `${row.client_id} ${row.client_name}`,
    ...row.cells.map((c) => cellLabel(c)),
  ]);
  const widths = header.map((h, i) => Math.max(h.length, ...rows.map((r) => r[i]!.length)));
  const formatRow = (cols: string[]) => cols.map((c, i) => c.padEnd(widths[i]!)).join("  ");

  return [formatRow(header), widths.map((w) => "-".repeat(w)).join("  "), ...rows.map(formatRow)].join("\n");
}
