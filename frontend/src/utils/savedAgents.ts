import { useEffect, useSyncExternalStore } from 'react'
import { API_BASE } from '../types'
import type { ChildAgentNodeData, FlowEdge, FlowNode } from '../types'

/**
 * Saved agents (plan.md C11 step 2): a child agent saved with the tool, toolkit and skill nodes wired
 * to it. "Save as agent" builds the spec from the canvas; dropping a saved agent recreates those nodes
 * and edges. The server blanks credentials on save, so a dropped agent asks for its keys again.
 */
export interface SavedAgentSpec {
  child: Partial<ChildAgentNodeData>
  tools: { type: 'tool' | 'toolkit'; data: Record<string, any> }[]
  skills: Record<string, any>[]
}

export interface SavedAgent {
  id: string
  name: string
  icon: string
  description: string
  version: number
  spec: SavedAgentSpec
  updated_at: string
  /** Set on save: credential fields the server blanked */
  stripped?: string[]
}

// Canvas-only fields: identity, selection, debugging, callbacks
const CHILD_SKIP = new Set(['label', 'master_id', 'isSelected', 'onDelete', 'debug_pin', 'debug_breakpoint',
  'saved_agent_id', 'saved_agent_version', 'builtin_agent_id'])
const NODE_SKIP = new Set(['isSelected', 'onDelete', 'onDropTool', 'nodeId', 'debug_pin', 'debug_breakpoint'])

function plain(data: Record<string, any>, skip: Set<string>): Record<string, any> {
  return Object.fromEntries(Object.entries(data).filter(([k, v]) => !skip.has(k) && typeof v !== 'function'))
}

/** The spec "Save as agent" sends for a child node: its settings plus the nodes wired to it. */
export function buildAgentSpec(child: FlowNode, nodes: FlowNode[], edges: FlowEdge[]): SavedAgentSpec {
  const linked = new Set(edges
    .filter((e) => e.source === child.id || e.target === child.id)
    .map((e) => (e.source === child.id ? e.target : e.source)))
  const wired = nodes.filter((n) => linked.has(n.id))
  return {
    child: plain(child.data as Record<string, any>, CHILD_SKIP) as Partial<ChildAgentNodeData>,
    tools: wired
      .filter((n) => n.type === 'tool' || n.type === 'toolkit')
      .map((n) => ({ type: n.type as 'tool' | 'toolkit', data: plain(n.data as Record<string, any>, NODE_SKIP) })),
    skills: wired.filter((n) => n.type === 'skill').map((n) => plain(n.data as Record<string, any>, NODE_SKIP)),
  }
}

/** Nodes and edges for an agent spec dropped at ``position``: the child, its tools in a row below it
 *  and its skills to the right. ``childData`` is merged into the child (its label, where it came from).
 *  Callbacks (onDelete, onDropTool) are the caller's to attach. */
export function instantiateSpec(spec: SavedAgentSpec, position: { x: number; y: number }, idBase: string,
    childData: Record<string, unknown>): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const childId = idBase
  const child = {
    id: childId, type: 'child_agent', position,
    data: {
      master_id: '', role: 'Custom', provider: 'openai', model: 'gpt-4o', api_key: '',
      system_prompt: '', ...spec.child, allowed_tool_ids: spec.child.allowed_tool_ids ?? [],
      ...childData, isSelected: true,
    },
  } as FlowNode
  const tools = spec.tools.map((t, i) => ({
    id: `${idBase}-tool-${i}`, type: t.type,
    position: { x: position.x + i * 220, y: position.y + 260 },
    data: t.type === 'toolkit' ? { subTools: [], ...t.data } : { config: {}, ...t.data },
  }) as FlowNode)
  const skills = spec.skills.map((s, i) => ({
    id: `${idBase}-skill-${i}`, type: 'skill',
    position: { x: position.x + 360, y: position.y + i * 140 },
    data: { label: 'Skill', icon: '⚡', description: '', instructions: '', category: 'general', tool_ids: [], tags: [], ...s },
  }) as unknown as FlowNode)
  // Name the handles: without them React Flow uses each node's first handle, the child's left side
  const edges = [
    ...tools.map((n) => ({ id: `e-${childId}-${n.id}`, source: childId, sourceHandle: 'ca-source-bottom', target: n.id,
      targetHandle: n.type === 'toolkit' ? 'tk-target-top' : 'tool-target-top' })),
    ...skills.map((n) => ({ id: `e-${childId}-${n.id}`, source: childId, sourceHandle: 'ca-source-right', target: n.id,
      targetHandle: 'skill-target-left' })),
  ]
  return { nodes: [child, ...tools, ...skills], edges }
}

/** A saved agent dropped at ``position`` (see instantiateSpec). */
export function instantiateSavedAgent(agent: SavedAgent, position: { x: number; y: number }, idBase: string):
    { nodes: FlowNode[]; edges: FlowEdge[] } {
  return instantiateSpec(agent.spec, position, idBase,
    { label: agent.name, saved_agent_id: agent.id, saved_agent_version: agent.version })
}

// ── API + shared list ──────────────────────────────────────────────────────────

let agents: SavedAgent[] = []
let loaded = false
let inflight: Promise<void> | null = null
const listeners = new Set<() => void>()

function emit() { listeners.forEach((fn) => fn()) }
function subscribe(fn: () => void) { listeners.add(fn); return () => { listeners.delete(fn) } }
const getAgents = () => agents

export function refreshSavedAgents(): Promise<void> {
  if (inflight) return inflight
  inflight = fetch(`${API_BASE}/api/saved-agents`)
    .then((r) => (r.ok ? r.json() : []))
    .then((rows: SavedAgent[]) => { agents = Array.isArray(rows) ? rows : [] })
    .catch(() => { agents = [] })
    .finally(() => { loaded = true; inflight = null; emit() })
  return inflight
}

/** The project's saved agents, newest first; fetched once and refreshed after every save / delete. */
export function useSavedAgents(): readonly SavedAgent[] {
  useEffect(() => { if (!loaded) refreshSavedAgents() }, [])
  return useSyncExternalStore(subscribe, getAgents, getAgents)
}

async function send(url: string, method: string, body?: unknown): Promise<any> {
  const res = await fetch(url, {
    method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined,
  })
  const json = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(typeof json?.detail === 'string' ? json.detail : `Request failed (${res.status})`)
  await refreshSavedAgents()
  return json
}

export function saveAgent(fields: { name: string; icon?: string; description?: string; spec: SavedAgentSpec }): Promise<SavedAgent> {
  return send(`${API_BASE}/api/saved-agents`, 'POST', fields)
}

export function updateSavedAgent(id: string, fields: { name?: string; description?: string; spec?: SavedAgentSpec }): Promise<SavedAgent> {
  return send(`${API_BASE}/api/saved-agents/${encodeURIComponent(id)}`, 'PUT', fields)
}

export function deleteSavedAgent(id: string): Promise<void> {
  return send(`${API_BASE}/api/saved-agents/${encodeURIComponent(id)}`, 'DELETE')
}
