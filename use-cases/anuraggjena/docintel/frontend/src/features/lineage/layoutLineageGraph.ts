import type { Edge, Node } from '@xyflow/react'

import type { LineageEdge, LineageGraph, LineageNode } from '@/core/api/lineageApi'

import type { LineageNodeData } from './LineageNodeCard'

const NODE_WIDTH = 240
const NODE_HEIGHT = 90
const HORIZONTAL_GAP = 50
const VERTICAL_GAP = 100

function findFallbackRoot(nodes: LineageNode[], edges: LineageEdge[]): string | null {
  if (nodes.length === 0) return null

  const targets = new Set(edges.map((edge) => edge.target_id))
  const roots = nodes.filter((node) => !targets.has(node.id))
  if (roots.length === 1) return roots[0].id

  return nodes[0]?.id ?? null
}

function assignLevels(
  graph: LineageGraph
): Map<string, number> {
  const levels = new Map<string, number>()
  const adjacency = new Map<string, string[]>()

  for (const node of graph.nodes) {
    adjacency.set(node.id, [])
  }

  for (const edge of graph.edges) {
    adjacency.get(edge.source_id)?.push(edge.target_id)
  }

  const startId = graph.root_node_id ?? findFallbackRoot(graph.nodes, graph.edges)
  if (!startId) {
    for (const node of graph.nodes) {
      levels.set(node.id, 0)
    }
    return levels
  }

  const queue: string[] = [startId]
  levels.set(startId, 0)

  while (queue.length > 0) {
    const currentId = queue.shift()!
    const currentLevel = levels.get(currentId) ?? 0

    for (const neighborId of adjacency.get(currentId) ?? []) {
      if (!levels.has(neighborId)) {
        levels.set(neighborId, currentLevel + 1)
        queue.push(neighborId)
      }
    }
  }

  let nextLevel = Math.max(0, ...levels.values()) + 1
  for (const node of graph.nodes) {
    if (!levels.has(node.id)) {
      levels.set(node.id, nextLevel)
      nextLevel += 1
    }
  }

  return levels
}

export function layoutLineageGraph(graph: LineageGraph): {
  nodes: Node<LineageNodeData>[]
  edges: Edge[]
} {
  const levels = assignLevels(graph)
  const nodesByLevel = new Map<number, string[]>()

  for (const [nodeId, level] of levels) {
    const group = nodesByLevel.get(level) ?? []
    group.push(nodeId)
    nodesByLevel.set(level, group)
  }

  for (const group of nodesByLevel.values()) {
    group.sort()
  }

  const nodeById = new Map(graph.nodes.map((node) => [node.id, node]))

  const flowNodes: Node<LineageNodeData>[] = graph.nodes.map((node) => {
    const level = levels.get(node.id) ?? 0
    const group = nodesByLevel.get(level) ?? [node.id]
    const indexInLevel = group.indexOf(node.id)
    const countInLevel = group.length
    const totalWidth = countInLevel * NODE_WIDTH + Math.max(0, countInLevel - 1) * HORIZONTAL_GAP
    const x = indexInLevel * (NODE_WIDTH + HORIZONTAL_GAP) - totalWidth / 2 + NODE_WIDTH / 2
    const y = level * (NODE_HEIGHT + VERTICAL_GAP)

    return {
      id: node.id,
      type: 'lineage',
      position: { x, y },
      data: { lineageNode: nodeById.get(node.id) ?? node },
    }
  })

  const flowEdges: Edge[] = graph.edges.map((edge, index) => ({
    id: `edge-${edge.source_id}-${edge.target_id}-${index}`,
    source: edge.source_id,
    target: edge.target_id,
    label: edge.edge_type,
    type: 'smoothstep',
  }))

  return { nodes: flowNodes, edges: flowEdges }
}
