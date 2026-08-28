import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { deriveStageStatus } from "./stageDerivation";
import { STAGES } from "./constants";

/**
 * Property 10: Progress Stepper Stage Derivation
 *
 * For any pipeline state (current_node, completed_nodes), each stage SHALL be:
 * - "complete" if ALL its constituent nodes appear in completedNodes
 * - "in-progress" if currentNode is one of its constituent nodes (and not all complete)
 * - "pending" otherwise
 *
 * **Validates: Requirements 6.3, 6.4, 6.5**
 */

// Collect all possible node names from STAGES
const ALL_NODES = STAGES.flatMap((stage) => stage.nodes);

describe("Property 10: Progress Stepper Stage Derivation", () => {
  it("marks a stage as 'complete' when ALL its nodes are in completedNodes", () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...STAGES),
        fc.shuffledSubarray(ALL_NODES),
        fc.constantFrom(null, ...ALL_NODES),
        (stage, completedSubset, currentNode) => {
          // Ensure ALL nodes of this stage are completed
          const completedNodes = [...new Set([...completedSubset, ...stage.nodes])];
          const result = deriveStageStatus(stage, completedNodes, currentNode);
          expect(result).toBe("complete");
        }
      ),
      { numRuns: 100 }
    );
  });

  it("marks a stage as 'in-progress' when currentNode is one of its nodes and not all nodes are complete", () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...STAGES.filter((s) => s.nodes.length > 1)),
        fc.shuffledSubarray(ALL_NODES),
        (stage, completedSubset) => {
          // Remove at least the last node of this stage to ensure not all are complete
          const completedNodes = completedSubset.filter(
            (n) => !(stage.nodes.includes(n) && n === stage.nodes[stage.nodes.length - 1])
          );
          const allComplete = stage.nodes.every((n) => completedNodes.includes(n));
          if (allComplete) return; // skip if accidentally all complete

          // Pick a node from this stage as currentNode
          const currentNode = stage.nodes[0];
          const result = deriveStageStatus(stage, completedNodes, currentNode);
          expect(result).toBe("in-progress");
        }
      ),
      { numRuns: 100 }
    );
  });

  it("marks a stage as 'pending' when currentNode is not one of its nodes and not all nodes are complete", () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...STAGES),
        fc.shuffledSubarray(ALL_NODES),
        (stage, completedSubset) => {
          // Ensure NOT all stage nodes are in completedNodes
          const completedNodes = completedSubset.filter(
            (n) => !(stage.nodes.includes(n) && n === stage.nodes[stage.nodes.length - 1])
          );
          const allComplete = stage.nodes.every((n) => completedNodes.includes(n));
          if (allComplete) return; // skip if accidentally all complete

          // Pick a currentNode that is NOT in this stage (or null)
          const otherNodes = ALL_NODES.filter((n) => !stage.nodes.includes(n));
          const currentNode = otherNodes.length > 0 ? otherNodes[0] : null;

          const result = deriveStageStatus(stage, completedNodes, currentNode);
          expect(result).toBe("pending");
        }
      ),
      { numRuns: 100 }
    );
  });

  it("'complete' takes priority over 'in-progress' — if all nodes done AND current is in stage, returns 'complete'", () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...STAGES),
        fc.shuffledSubarray(ALL_NODES),
        (stage, extraCompleted) => {
          // All stage nodes are completed
          const completedNodes = [...new Set([...extraCompleted, ...stage.nodes])];
          // currentNode is one of the stage's nodes
          const currentNode = stage.nodes[0];
          const result = deriveStageStatus(stage, completedNodes, currentNode);
          expect(result).toBe("complete");
        }
      ),
      { numRuns: 100 }
    );
  });

  it("correctly derives status for any arbitrary pipeline state", () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...STAGES),
        fc.shuffledSubarray(ALL_NODES),
        fc.constantFrom(null, ...ALL_NODES),
        (stage, completedNodes, currentNode) => {
          const result = deriveStageStatus(stage, completedNodes, currentNode);

          const allComplete = stage.nodes.every((n) => completedNodes.includes(n));
          const hasRunning = currentNode !== null && stage.nodes.includes(currentNode);

          if (allComplete) {
            expect(result).toBe("complete");
          } else if (hasRunning) {
            expect(result).toBe("in-progress");
          } else {
            expect(result).toBe("pending");
          }
        }
      ),
      { numRuns: 100 }
    );
  });
});
