import { useMemo } from 'react'
import {
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  ReactFlow,
  ReactFlowProvider,
} from '@xyflow/react'
import type { Edge, Node, NodeMouseHandler } from '@xyflow/react'
import { nodeTypes } from '../nodes'

interface Props {
  nodes: Node[]
  edges: Edge[]
  onNodeClick?: NodeMouseHandler
}

/** A non-editable canvas that renders a flow with the real node components. */
export function ReadOnlyFlow({ nodes: rawNodes, edges: rawEdges, onNodeClick }: Props) {
  const nodes = useMemo<Node[]>(
    () => rawNodes.map((n) => ({
      ...n,
      selected: false,
      draggable: false,
      connectable: false,
      data: { ...n.data, isSelected: false, onDelete: undefined },
    })),
    [rawNodes],
  )
  const edges = useMemo<Edge[]>(
    () => rawEdges.map((e) => ({
      ...e,
      type: undefined,   // plain edges — no delete buttons in a read-only view
      deletable: false,
      markerEnd: e.markerEnd ?? { type: MarkerType.ArrowClosed },
    })),
    [rawEdges],
  )

  return (
    <ReactFlowProvider>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        deleteKeyCode={null}
        onNodeClick={onNodeClick}
        fitView
        fitViewOptions={{ maxZoom: 1, padding: 0.2 }}
        minZoom={0.2}
        maxZoom={1.75}
        proOptions={{ hideAttribution: true }}
        className="flow-surface"
      >
        <Controls showInteractive={false} />
        <Background variant={BackgroundVariant.Dots} gap={20} size={1.2} color="var(--canvas-dot)" />
      </ReactFlow>
    </ReactFlowProvider>
  )
}
