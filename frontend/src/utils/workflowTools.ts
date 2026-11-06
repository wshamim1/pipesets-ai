import type { Edge, Node } from '@xyflow/react'
import type { ToolNodeData } from '../types'

/** The tool node wired to a workflow step (either direction), mirroring how the backend resolves it. */
export function findLinkedTool(stepId: string, nodes: Node[], edges: Edge[]): ToolNodeData | null {
  for (const e of edges) {
    const otherId = e.source === stepId ? e.target : e.target === stepId ? e.source : null
    const other = otherId ? nodes.find((n) => n.id === otherId) : undefined
    if (other?.type === 'tool') return other.data as ToolNodeData
  }
  return null
}
