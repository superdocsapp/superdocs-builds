import type { StageDefinition } from "@/utils/constants";

export type StageStatus = "complete" | "in-progress" | "pending";

/**
 * Derives the visual status of a pipeline stage based on completed nodes
 * and the currently running node.
 *
 * - "complete"     → all nodes in the stage appear in completedNodes
 * - "in-progress"  → currentNode is one of the stage's nodes
 * - "pending"      → otherwise
 */
export function deriveStageStatus(
  stage: StageDefinition,
  completedNodes: string[],
  currentNode: string | null
): StageStatus {
  const allComplete = stage.nodes.every((n) => completedNodes.includes(n));
  if (allComplete) return "complete";

  const hasRunning =
    currentNode !== null && stage.nodes.includes(currentNode);
  if (hasRunning) return "in-progress";

  return "pending";
}
