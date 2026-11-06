import type { FlowEdge, FlowNode } from '../types'

/** Node and edge builders the blueprint files share. */

export const edge = (id: string, source: string, target: string): FlowEdge => ({ id, source, target })

export const llm = (label: string, system_prompt: string, temperature = 0.7) => ({
  label, provider: 'openai', model: 'gpt-4o',
  temperature, max_tokens: 1024, top_p: 1.0, api_key: '', system_prompt, base_url: '',
})

export const child = (label: string, role: string, system_prompt: string, allowed_tool_ids: string[] = []) => ({
  label, master_id: 'master-1', role, provider: 'openai', model: 'gpt-4o', api_key: '', allowed_tool_ids, system_prompt,
})

/** A tool node; settings start from the tool's catalog defaults. */
export const tool = (id: string, x: number, y: number, label: string, toolId: string, icon: string, description: string,
  config: Record<string, unknown>, toolType: 'tool' | 'mcp' = 'tool'): FlowNode =>
  ({ id, type: 'tool', position: { x, y }, data: { label, toolId, toolType, icon, description, config } }) as FlowNode

export const start = (y = 300): FlowNode => ({ id: 'start-1', type: 'start', position: { x: 60, y }, data: { label: 'Start' } })

export const stop = (x: number, y = 300): FlowNode => ({ id: 'stop-1', type: 'stop', position: { x, y }, data: { label: 'Stop' } })

export const slack = (id: string, x: number, y: number, channel: string) => tool(id, x, y, 'Slack Webhook', 'slack_webhook', '💬',
  'Posts messages to Slack via an incoming webhook URL.', { webhook_url: '', channel, username: 'Pipesets' })

type Side = 'left' | 'right' | 'top' | 'bottom'

/** Handle id prefix per node type — each node component names its handles ``<prefix>-<source|target>-<side>``. */
const HANDLE_PREFIX: Record<string, string> = {
  llm: 'llm', tool: 'tool', toolkit: 'tk', memory: 'mem', cache: 'cache', doc_loader: 'dl', text_splitter: 'ts',
  embedding: 'emb', vector_store: 'vs', retriever: 'ret', reranker: 'rer', master_agent: 'ma', child_agent: 'ca',
  connection: 'conn', knowledge_base: 'kb', start: 'start', stop: 'stop', skill: 'skill', human_gate: 'hg',
  checkpointer: 'cp', wf_step: 'wf', output_parser: 'op', middleware: 'mw', synthetic_data: 'syn',
}

/** Sides a node type has handles on, where it isn't all four */
const SOURCE_SIDES: Record<string, Side[]> = { start: ['right', 'bottom'], stop: [] }
const TARGET_SIDES: Record<string, Side[]> = { start: [], stop: ['left', 'top'] }

/** Node types a caller uses rather than passes the run on to */
const ATTACHMENTS = new Set(['tool', 'toolkit', 'memory', 'cache', 'middleware', 'skill', 'knowledge_base', 'output_parser', 'checkpointer'])

const OPPOSITE:Record<Side, Side> = { left: 'right', right: 'left', top: 'bottom', bottom: 'top' }

/**
 * Fills in ``sourceHandle``/``targetHandle`` on edges that leave them out, using the side of each node that faces
 * the other. Without them React Flow attaches the edge to the node's first handle — the left one — so edges
 * loop back round their source node.
 */
export function wireHandles(nodes: FlowNode[], edges: FlowEdge[]): FlowEdge[] {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  return edges.map((e) => {
    const s = byId.get(e.source), t = byId.get(e.target)
    const sp = HANDLE_PREFIX[s?.type ?? ''], tp = HANDLE_PREFIX[t?.type ?? '']
    if (!s || !t || !sp || !tp) return e
    const dx = t.position.x - s.position.x, dy = t.position.y - s.position.y
    // Tools, memory, skills… hang in rows above/below the node using them, so those edges run vertically
    const attached = ATTACHMENTS.has(s.type!) || ATTACHMENTS.has(t.type!)
    const vertical = attached ? Math.abs(dy) >= 150 : Math.abs(dy) > Math.abs(dx)
    const facing: Side = vertical ? (dy >= 0 ? 'bottom' : 'top') : (dx >= 0 ? 'right' : 'left')
    const pick = (want: Side, sides: Side[] | undefined) => (!sides || sides.includes(want) ? want : sides[0])
    const from = pick(facing, SOURCE_SIDES[s.type!]), to = pick(OPPOSITE[facing], TARGET_SIDES[t.type!])
    return {
      ...e,
      sourceHandle: e.sourceHandle ?? (from && `${sp}-source-${from}`),
      targetHandle: e.targetHandle ?? (to && `${tp}-target-${to}`),
    }
  })
}
