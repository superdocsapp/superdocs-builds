/**
 * Custom DAG layout for the pipeline canvas.
 * Uses topological sort + rank assignment to compute positions.
 * No eval() or Function() — CSP-safe.
 *
 * Parallel branches (nodes at the same rank) are placed side by side.
 * Merges converge visually because they're assigned to the next rank after
 * all their predecessors.
 */
import type { Node, Edge } from '@xyflow/react';

export interface LayoutOptions {
  /** Horizontal gap between sibling nodes at the same rank (pixels) */
  nodesep?: number;
  /** Vertical gap between ranks/layers (pixels) */
  ranksep?: number;
}

const DEFAULTS: Required<LayoutOptions> = {
  nodesep: 100,
  ranksep: 120,
};

/** Estimated node dimensions for centering */
const NODE_WIDTH = 180;
const NODE_HEIGHT = 56;

/**
 * Assigns each node a rank (layer/depth) based on longest-path from sources.
 * This ensures merge nodes sit below all of their inputs.
 */
function assignRanks(
  nodeIds: string[],
  adjacency: Map<string, string[]>,
  inDegree: Map<string, number>
): Map<string, number> {
  const rank = new Map<string, number>();
  // BFS-like: start from sources (inDegree 0)
  const queue: string[] = [];

  for (const id of nodeIds) {
    if ((inDegree.get(id) ?? 0) === 0) {
      queue.push(id);
      rank.set(id, 0);
    }
  }

  // Longest-path approach: each node's rank = max(predecessor ranks) + 1
  // Process in topological order
  const visited = new Set<string>();
  const topoOrder: string[] = [];

  // Kahn's algorithm for topo sort
  const inDeg = new Map(inDegree);
  const q = [...queue];
  while (q.length > 0) {
    const node = q.shift()!;
    topoOrder.push(node);
    visited.add(node);
    for (const neighbor of adjacency.get(node) ?? []) {
      const deg = (inDeg.get(neighbor) ?? 1) - 1;
      inDeg.set(neighbor, deg);
      if (deg === 0) {
        q.push(neighbor);
      }
    }
  }

  // Assign ranks via longest path
  for (const id of nodeIds) {
    if (!rank.has(id)) rank.set(id, 0);
  }

  for (const node of topoOrder) {
    const currentRank = rank.get(node) ?? 0;
    for (const neighbor of adjacency.get(node) ?? []) {
      const existing = rank.get(neighbor) ?? 0;
      rank.set(neighbor, Math.max(existing, currentRank + 1));
    }
  }

  return rank;
}

/**
 * Runs a simple layered graph layout and returns nodes with updated positions.
 * Nodes in the same rank are placed horizontally centered.
 */
export function applyDagreLayout(
  nodes: Node[],
  edges: Edge[],
  options?: LayoutOptions
): Node[] {
  const opts = { ...DEFAULTS, ...options };

  const nodeIds = nodes.map((n) => n.id);
  const adjacency = new Map<string, string[]>();
  const inDegree = new Map<string, number>();

  // Initialize
  for (const id of nodeIds) {
    adjacency.set(id, []);
    inDegree.set(id, 0);
  }

  // Build adjacency + in-degree from edges
  for (const edge of edges) {
    // Only process edges between known nodes
    if (adjacency.has(edge.source) && inDegree.has(edge.target)) {
      adjacency.get(edge.source)!.push(edge.target);
      inDegree.set(edge.target, (inDegree.get(edge.target) ?? 0) + 1);
    }
  }

  const ranks = assignRanks(nodeIds, adjacency, inDegree);

  // Group nodes by rank
  const rankGroups = new Map<number, string[]>();
  for (const [id, r] of ranks) {
    if (!rankGroups.has(r)) rankGroups.set(r, []);
    rankGroups.get(r)!.push(id);
  }

  // Compute positions
  const positions = new Map<string, { x: number; y: number }>();
  const maxRank = Math.max(...ranks.values(), 0);

  for (let r = 0; r <= maxRank; r++) {
    const group = rankGroups.get(r) ?? [];
    const count = group.length;
    // Center the group horizontally
    const totalWidth = count * NODE_WIDTH + (count - 1) * opts.nodesep;
    const startX = -totalWidth / 2;

    for (let i = 0; i < count; i++) {
      positions.set(group[i], {
        x: startX + i * (NODE_WIDTH + opts.nodesep),
        y: r * (NODE_HEIGHT + opts.ranksep),
      });
    }
  }

  return nodes.map((node) => {
    const pos = positions.get(node.id) ?? { x: 0, y: 0 };
    return {
      ...node,
      position: pos,
    };
  });
}
