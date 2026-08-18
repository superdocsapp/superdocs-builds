import { createHash, randomUUID } from "node:crypto";
import { mkdir, rename, writeFile } from "node:fs/promises";
import { join } from "node:path";

import { redactSecrets } from "./errors";
import type { JobSnapshot, PendingChange } from "./types";

export type ProposalTargetClassification = {
  target: "body" | "header" | "footer";
  reason: string;
};

export type ProposalEvidenceOptions = {
  evidenceDirectory?: string;
};

export async function persistPendingProposalEvidence(
  snapshot: JobSnapshot,
  options: ProposalEvidenceOptions = {},
): Promise<string> {
  const configuredDirectory =
    process.env.POLICYSET_PROPOSAL_EVIDENCE_DIR?.trim();
  const directory =
    options.evidenceDirectory ??
    (configuredDirectory ||
      join(process.cwd(), "tmp", "policyset-proposal-evidence"));
  const fileKey = createHash("sha256")
    .update(snapshot.reference.jobId)
    .digest("hex")
    .slice(0, 24);
  const filename = `proposal-${fileKey}.json`;
  const destination = join(directory, filename);
  const temporary = join(
    directory,
    `.${filename}.${process.pid}.${randomUUID()}.tmp`,
  );
  const evidence = {
    schema_version: 1,
    captured_at: new Date().toISOString(),
    job_id: redactSecrets(snapshot.reference.jobId),
    proposals: snapshot.pendingChanges.map(sanitizedProposalEvidence),
  };

  await mkdir(directory, { recursive: true, mode: 0o700 });
  await writeFile(temporary, `${JSON.stringify(evidence, null, 2)}\n`, {
    encoding: "utf8",
    mode: 0o600,
  });
  await rename(temporary, destination);
  return destination;
}

export function classifyProposalTarget(
  proposal: Pick<PendingChange, "chunkId" | "oldHtml" | "newHtml">,
): ProposalTargetClassification {
  const chunkTarget = targetFromChunkIdentity(proposal.chunkId);
  if (chunkTarget) {
    return {
      target: chunkTarget,
      reason: `chunk_id structurally identifies a ${chunkTarget} target.`,
    };
  }

  for (const [field, html] of [
    ["old_html", proposal.oldHtml],
    ["new_html", proposal.newHtml],
  ] as const) {
    if (!html) {
      continue;
    }
    const root = firstOpeningTag(html);
    const rootTarget = root ? structuralTarget(root) : null;
    if (rootTarget) {
      return {
        target: rootTarget,
        reason: `${field} root element structurally identifies a ${rootTarget} target.`,
      };
    }

    const targeted = proposal.chunkId
      ? openingTagForChunk(html, proposal.chunkId)
      : null;
    const targetedType = targeted ? structuralTarget(targeted) : null;
    if (targetedType) {
      return {
        target: targetedType,
        reason: `${field} element matching chunk_id structurally identifies a ${targetedType} target.`,
      };
    }
  }

  return {
    target: "body",
    reason:
      "No targeted chunk identity or targeted/root structural metadata identifies header or footer content.",
  };
}

function sanitizedProposalEvidence(change: PendingChange) {
  const classification = classifyProposalTarget(change);
  return {
    change_id: redactSecrets(change.changeId),
    document_id: redactSecrets(change.documentId),
    chunk_id: nullableRedacted(change.chunkId),
    operation: change.operation,
    old_html: nullableRedacted(change.oldHtml),
    new_html: nullableRedacted(change.newHtml),
    ai_explanation: nullableRedacted(change.aiExplanation),
    local_classification: classification.target,
    local_reason: classification.reason,
  };
}

function targetFromChunkIdentity(
  chunkId: string | null,
): "header" | "footer" | null {
  if (!chunkId) {
    return null;
  }
  const match =
    /(?:^|[/:._-])(header|footer|hdr|ftr)(?:[/:._-]|$)/i.exec(chunkId);
  if (!match) {
    return null;
  }
  const value = match[1].toLowerCase();
  return value === "header" || value === "hdr" ? "header" : "footer";
}

type OpeningTag = {
  name: string;
  attributes: string;
};

function firstOpeningTag(html: string): OpeningTag | null {
  const match = /<([a-z][\w:-]*)(\s[^>]*)?>/i.exec(html);
  return match
    ? { name: match[1].toLowerCase(), attributes: match[2] ?? "" }
    : null;
}

function openingTagForChunk(
  html: string,
  chunkId: string,
): OpeningTag | null {
  const escaped = escapeRegExp(chunkId);
  const matcher = new RegExp(
    `<([a-z][\\w:-]*)(\\s[^>]*(?:data-chunk-id|data-node-id|data-id|id)=["']${escaped}["'][^>]*)>`,
    "i",
  );
  const match = matcher.exec(html);
  return match
    ? { name: match[1].toLowerCase(), attributes: match[2] ?? "" }
    : null;
}

function structuralTarget(
  tag: OpeningTag,
): "header" | "footer" | null {
  if (tag.name === "header" || tag.name === "w:hdr") {
    return "header";
  }
  if (tag.name === "footer" || tag.name === "w:ftr") {
    return "footer";
  }

  const attributes = [
    "data-part-type",
    "data-superdoc-part",
    "data-section-type",
    "data-region",
    "data-node-type",
    "data-content-type",
    "part-type",
  ];
  for (const attribute of attributes) {
    const match = new RegExp(
      `(?:^|\\s)${attribute}=["']([^"']+)["']`,
      "i",
    ).exec(tag.attributes);
    const target = match ? targetFromStructuralValue(match[1]) : null;
    if (target) {
      return target;
    }
  }
  return null;
}

function targetFromStructuralValue(
  value: string,
): "header" | "footer" | null {
  const match =
    /(?:^|[/:._-])(header|footer|hdr|ftr)(?:[/:._-]|$)/i.exec(value);
  if (!match) {
    return null;
  }
  const token = match[1].toLowerCase();
  return token === "header" || token === "hdr" ? "header" : "footer";
}

function nullableRedacted(value: string | null): string | null {
  return value === null ? null : redactSecrets(value);
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
