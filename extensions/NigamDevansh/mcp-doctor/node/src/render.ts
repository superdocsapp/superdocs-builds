// Turning a report into something a human reads.
//
// The healthy case deserves to be boring: one line per client. A failure is a
// numbered list, worst first, each with the cause and what to do about it.

import type { RepairResult } from "./repair.js";
import type { Report, Severity } from "./types.js";

const MARK: Record<Severity, string> = { error: "✗", warn: "!", info: "i" };

export function renderText(report: Report, useColour: boolean): string {
  const lines: string[] = [];
  const dim = (s: string) => (useColour ? `\x1b[2m${s}\x1b[0m` : s);
  const bold = (s: string) => (useColour ? `\x1b[1m${s}\x1b[0m` : s);

  const scanned = report.clients.filter((c) =>
    c.config_files.some((f) => f.status !== "absent"),
  );

  if (scanned.length === 0) {
    lines.push("No MCP client configuration found.");
    lines.push(dim("  Looked for: " + report.clients.map((c) => c.name).join(", ")));
    return lines.join("\n");
  }

  for (const client of scanned) {
    const own = report.findings.filter((f) => f.client === client.name);
    const files = client.config_files.filter((f) => f.status !== "absent");

    if (own.length === 0) {
      lines.push(`${bold(client.name)}: configuration looks correct`);
    } else {
      lines.push(bold(client.name));
    }
    for (const file of files) {
      const entries = file.entries?.length ?? 0;
      lines.push(dim(`  ${file.path} (${file.format}, ${entries} SuperDocs entr${entries === 1 ? "y" : "ies"})`));
    }
    // `documented`/`unverified` is worth saying out loud: it tells the reader
    // how much the tool actually knows about their client.
    if (client.evidence_tier !== "captured") {
      lines.push(dim(`  client knowledge: ${client.evidence_tier}`));
    }
    for (const f of own) {
      lines.push(`  ${MARK[f.severity]} ${f.message}`);
      if (f.remediation) lines.push(dim(`      → ${f.remediation}`));
    }
    lines.push("");
  }

  const { errors, warnings } = report.summary;
  if (errors === 0 && warnings === 0) {
    lines.push("Nothing to report.");
  } else {
    const parts: string[] = [];
    if (errors) parts.push(`${errors} error${errors === 1 ? "" : "s"}`);
    if (warnings) parts.push(`${warnings} warning${warnings === 1 ? "" : "s"}`);
    lines.push(parts.join(", "));
  }

  // Say plainly that repair is unavailable, rather than letting a remediation
  // point at a command that exits 2. Derived from write_capable, which both
  // implementations read, so the two stay in step.
  const repairable = report.findings.some((f) => f.auto_fixable);
  const anyWritable = report.clients.some((c) => c.write_capable);
  if (repairable && !anyWritable) {
    lines.push(
      dim("Automatic repair is not available yet; these must be corrected by hand."),
    );
  }

  // Evidence tiers are worth stating once, at the end: they tell the reader how
  // much this tool actually knows about their client.
  const unproven = scanned.filter((c) => c.evidence_tier !== "captured");
  if (unproven.length > 0) {
    lines.push(
      dim(
        `Read-only and experimental for: ${unproven.map((c) => c.name).join(", ")} ` +
          `(client knowledge not yet captured from a real install).`,
      ),
    );
  }

  return lines.join("\n").trimEnd();
}

export function renderJson(report: Report): string {
  return JSON.stringify(report, null, 2);
}

/** The --fix run: what was written, what was refused, and why. */
export function renderRepair(result: RepairResult): string {
  const lines: string[] = [];

  for (const file of result.files) {
    if (file.backup) {
      lines.push(`✓ ${file.client}: backed up → ${file.backup.path}`);
      if (file.backup.gitWarning) {
        for (const line of file.backup.gitWarning.split("\n")) lines.push(`  ! ${line}`);
      }
    }
    for (const fix of file.applied) {
      lines.push(`✓ ${file.client}: ${fix.description}`);
    }
    // A refusal is the interesting output when nothing is write-capable, so it
    // gets the reason rather than a bare "skipped".
    for (const refusal of file.refused) {
      lines.push(`i ${file.client}: ${refusal.findingId} not repaired — ${refusal.reason}`);
    }
    if (file.error) lines.push(`✗ ${file.client}: ${file.error}`);
  }

  const fixed = result.files.reduce((n, f) => n + f.applied.length, 0);
  const remaining = result.after.summary.errors;

  if (lines.length === 0) lines.push("Nothing to repair.");
  lines.push("");
  if (fixed > 0) lines.push(`${fixed} change${fixed === 1 ? "" : "s"} written.`);
  if (remaining > 0) {
    lines.push(
      `${remaining} issue${remaining === 1 ? "" : "s"} still need${remaining === 1 ? "s" : ""} a human.`,
    );
  } else if (fixed > 0) {
    lines.push("Nothing left to fix.");
  }
  return lines.join("\n").trimEnd();
}

/** A shareable summary. Assembled from the redacted report, never from a fuller
 *  text, so there is no path by which a credential reaches it. */
export function renderReport(report: Report): string {
  const lines: string[] = ["# mcp-doctor report", ""];
  lines.push(`- tool: ${report.tool.name} ${report.tool.version} (${report.tool.implementation})`);
  lines.push(`- clients scanned: ${report.summary.clients_scanned}`);
  lines.push(`- files read: ${report.summary.config_files_read}`);
  lines.push(`- errors: ${report.summary.errors}, warnings: ${report.summary.warnings}`);
  lines.push("");

  for (const client of report.clients) {
    const files = client.config_files.filter((f) => f.status !== "absent");
    if (files.length === 0) continue;
    lines.push(`## ${client.name}`);
    lines.push("");
    lines.push(`- client knowledge: ${client.evidence_tier}`);
    lines.push(`- write capable: ${client.write_capable ? "yes" : "no"}`);
    for (const file of files) {
      lines.push(`- \`${file.path}\` — ${file.format}, ${file.status}`);
      for (const entry of file.entries ?? []) {
        // Host only, never the URL.
        const where = entry.host ? ` → ${entry.host}` : "";
        lines.push(`  - \`${entry.name}\` (${entry.kind}${where})`);
      }
    }
    const own = report.findings.filter((f) => f.client === client.name);
    if (own.length) {
      lines.push("");
      for (const f of own) lines.push(`- **${f.severity}** \`${f.id}\` — ${f.message}`);
    }
    lines.push("");
  }
  return lines.join("\n").trimEnd() + "\n";
}
