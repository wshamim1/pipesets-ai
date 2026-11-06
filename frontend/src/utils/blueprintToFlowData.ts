import type { AppRecord, FlowNode, FlowEdge } from '../types'
import { resolveDocLoaderType } from './docLoaders'

/** Map free-form loader names the LLM may emit onto the values the UI supports. */
export function normalizeNodeData(type: string | undefined, data: Record<string, any>): Record<string, any> {
  if (type !== 'doc_loader') return data
  const loader_type = resolveDocLoaderType(data.loader_type, data.source)
  return { ...data, loader_type, chunk_strategy: data.chunk_strategy || 'fixed', source: data.source ?? '' }
}

interface RawBlueprint {
  nodes?: Array<{ id?: string; type?: string; position?: { x?: number; y?: number }; data?: Record<string, any> }>
  edges?: Array<{ id?: string; source?: string; target?: string }>
}

/**
 * Convert an AI-generated blueprint into plain, persistable flow data
 * (no callbacks). App.tsx re-attaches onDelete/onDropTool when the app is loaded.
 */
export function blueprintToFlowData(blueprint: RawBlueprint | undefined): AppRecord['flow_data'] | null {
  const rawNodes = Array.isArray(blueprint?.nodes) ? blueprint!.nodes! : []
  const rawEdges = Array.isArray(blueprint?.edges) ? blueprint!.edges! : []
  if (rawNodes.length === 0) return null

  const ts = Date.now()
  const idMap = new Map<string, string>()

  const nodes = rawNodes.map((n, idx) => {
    const originalId = (n.id || `gen-node-${idx}`).trim()
    const mappedId = `node-${ts}-${idx}`
    idMap.set(originalId, mappedId)
    const data = normalizeNodeData(n.type, { ...(n.data || {}) })
    if (n.type === 'toolkit' && !Array.isArray(data.subTools)) data.subTools = []
    return {
      id: mappedId,
      type: (n.type || 'llm') as FlowNode['type'],
      position: {
        x: Number(n.position?.x ?? 220 + idx * 40),
        y: Number(n.position?.y ?? 180 + idx * 28),
      },
      data,
    } as FlowNode
  })

  const edges: FlowEdge[] = []
  rawEdges.forEach((e, idx) => {
    const source = e.source ? idMap.get(e.source) : undefined
    const target = e.target ? idMap.get(e.target) : undefined
    if (source && target) edges.push({ id: e.id || `edge-${ts}-${idx}`, source, target })
  })

  return { nodes, edges }
}
