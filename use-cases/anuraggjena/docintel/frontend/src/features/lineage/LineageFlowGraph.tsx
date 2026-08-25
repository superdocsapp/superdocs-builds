import { useEffect, useMemo, useState } from 'react'
import {
  Background,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  type Node,
  type NodeMouseHandler,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import type { LineageGraph, LineageNode } from '@/core/api/lineageApi'

import { LineageDetailDrawer } from './LineageDetailDrawer'
import { LineageNodeCard, type LineageNodeData } from './LineageNodeCard'
import { layoutLineageGraph } from './layoutLineageGraph'

const nodeTypes = {
  lineage: LineageNodeCard,
}

interface LineageFlowGraphProps {
  graph: LineageGraph
}

function LineageFlowGraphInner({ graph }: LineageFlowGraphProps) {
  const [selectedNode, setSelectedNode] = useState<LineageNode | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

  const { nodes: initialNodes, edges: initialEdges } = useMemo(
    () => layoutLineageGraph(graph),
    [graph]
  )

  const [nodes, setNodes] = useState<Node<LineageNodeData>[]>(initialNodes)

  useEffect(() => {
    setNodes(
      initialNodes.map((node) => ({
        ...node,
        selected: selectedNode?.id === node.id,
      }))
    )
  }, [initialNodes, selectedNode])

  const nodesById = useMemo(
    () => new Map(graph.nodes.map((node) => [node.id, node])),
    [graph.nodes]
  )

  const handleNodeClick: NodeMouseHandler<Node<LineageNodeData>> = (_event, node) => {
    const lineageNode = nodesById.get(node.id)
    if (!lineageNode) return
    setSelectedNode(lineageNode)
    setDrawerOpen(true)
  }

  const handleDrawerOpenChange = (open: boolean) => {
    setDrawerOpen(open)
    if (!open) {
      setSelectedNode(null)
    }
  }

  return (
    <>
      <div className="h-[600px] w-full rounded-lg border bg-background">
        <ReactFlow
          nodes={nodes}
          edges={initialEdges}
          nodeTypes={nodeTypes}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable
          fitView
          fitViewOptions={{ padding: 0.2 }}
          onNodeClick={handleNodeClick}
          proOptions={{ hideAttribution: true }}
        >
          <Controls showInteractive={false} />
          <Background gap={16} size={1} />
        </ReactFlow>
      </div>

      <LineageDetailDrawer
        open={drawerOpen}
        onOpenChange={handleDrawerOpenChange}
        node={selectedNode}
        edges={graph.edges}
        nodesById={nodesById}
      />
    </>
  )
}

export function LineageFlowGraph(props: LineageFlowGraphProps) {
  return (
    <ReactFlowProvider>
      <LineageFlowGraphInner {...props} />
    </ReactFlowProvider>
  )
}
