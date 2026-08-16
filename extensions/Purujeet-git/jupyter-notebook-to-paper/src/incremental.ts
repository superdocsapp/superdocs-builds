import type {
  Evidence,
  EvidenceChange,
  EvidenceSnapshot,
  IncrementalDiff,
  PaperDocument,
} from "./types.js";

export function createSnapshot(
  version: string,
  notebookPath: string,
  evidence: Evidence[],
): EvidenceSnapshot {
  return {
    version,
    notebookPath,
    evidence: [...evidence],
    generatedAt: new Date().toISOString(),
  };
}

export function diffEvidence(
  before: EvidenceSnapshot | undefined,
  after: EvidenceSnapshot,
  paper: PaperDocument,
): IncrementalDiff {
  const beforeMap = new Map((before?.evidence ?? []).map((item) => [item.id, item]));
  const afterMap = new Map(after.evidence.map((item) => [item.id, item]));
  const changes: EvidenceChange[] = [];

  for (const [id, next] of afterMap) {
    const previous = beforeMap.get(id);

    if (!previous) {
      changes.push({ evidenceId: id, kind: "added", after: next });
      continue;
    }

    if (previous.fingerprint !== next.fingerprint) {
      changes.push({
        evidenceId: id,
        kind: "changed",
        before: previous,
        after: next,
      });
    }
  }

  for (const [id, previous] of beforeMap) {
    if (!afterMap.has(id)) {
      changes.push({ evidenceId: id, kind: "removed", before: previous });
    }
  }

  const affectedEvidenceIds = [...new Set(changes.map((change) => change.evidenceId))];
  const affectedBlockIds = paper.blocks
    .filter((block) =>
      block.evidenceIds.some((evidenceId) => affectedEvidenceIds.includes(evidenceId))
    )
    .map((block) => block.id);

  return {
    changes,
    affectedEvidenceIds,
    affectedBlockIds,
  };
}

/**
 * Rebuilds only blocks whose evidence changed. Existing unaffected blocks are
 * reused by object identity, which also makes their serialized content stable.
 */
export function mergeIncrementalPaper(
  previous: PaperDocument,
  regenerated: PaperDocument,
  affectedBlockIds: string[],
): PaperDocument {
  const affected = new Set(affectedBlockIds);
  const previousById = new Map(previous.blocks.map((block) => [block.id, block]));
  return {
    title: regenerated.title,
    blocks: regenerated.blocks.map((block) => {
      const previousBlock = previousById.get(block.id);
      return previousBlock && !affected.has(block.id) ? previousBlock : block;
    }),
  };
}
