import { useEffect, useSyncExternalStore } from 'react'
import { API_BASE } from '../types'
import type { ToolCatalogItem } from '../types'
import type { SavedAgentSpec } from './savedAgents'

/**
 * Built-in agents (backend/agents/, GET /api/agent-catalog): the sidebar's Agents section, the
 * Specialist Role dropdown and the prompt a dropped starter begins with all read this, and
 * Settings → Agents installs them (plan.md C11 step 3).
 *
 * Starters are a role and a prompt (Researcher, Writer, …). Tool-backed agents list the tools they
 * need — each need met by any one of several tools — and drop as a child plus those tool nodes.
 */
export interface AgentToolNeed {
  ids: string[]
  optional: boolean
  why: string
  /** The installed tool that meets the need, if any */
  installed: string | null
  /** What a drop uses: the installed one, else the first option */
  use: string
  /** Tool id → its catalog name */
  names?: Record<string, string>
}

export interface BuiltinAgent {
  id: string
  name: string
  icon: string
  group: string
  description: string
  role: string
  system_prompt: string
  kind: 'llm' | 'external'
  starter: boolean
  tools: AgentToolNeed[]
  skills: string[]
  is_new: boolean
  extra: Record<string, unknown>
  /** Size of its eval set (tool-backed agents); "Create eval dataset" copies it */
  eval_cases: number
  ready: boolean
  missing_tools: string[]
  installed: boolean
  source: 'choice' | 'default' | 'in_use' | null
  in_use: boolean
}

export interface AgentCatalog {
  groups: string[]
  agents: BuiltinAgent[]
  can_edit: boolean
  can_install_tools: boolean
}

const EMPTY: AgentCatalog = { groups: [], agents: [], can_edit: false, can_install_tools: false }
let catalog: AgentCatalog = EMPTY
let loaded = false
let inflight: Promise<void> | null = null
const listeners = new Set<() => void>()

function emit() { listeners.forEach((fn) => fn()) }
function subscribe(fn: () => void) { listeners.add(fn); return () => { listeners.delete(fn) } }
const getCatalog = () => catalog

export function refreshAgentCatalog(): Promise<void> {
  if (inflight) return inflight
  inflight = fetch(`${API_BASE}/api/agent-catalog`)
    .then((r) => (r.ok ? r.json() : EMPTY))
    .then((c: AgentCatalog) => { catalog = Array.isArray(c?.agents) ? c : EMPTY })
    .catch(() => { catalog = EMPTY })
    .finally(() => { loaded = true; inflight = null; emit() })
  return inflight
}

/** For tests: use this catalog instead of fetching one. */
export function setAgentCatalog(c: AgentCatalog): void {
  catalog = c
  loaded = true
  emit()
}

export function useAgentCatalog(): AgentCatalog {
  useEffect(() => { if (!loaded) refreshAgentCatalog() }, [])
  return useSyncExternalStore(subscribe, getCatalog, getCatalog)
}

/** Roles offered in a child agent's Specialist Role dropdown: the starter roles that run a model. */
export function agentRoles(c: AgentCatalog = catalog): string[] {
  const roles = c.agents.filter((a) => a.starter && a.kind === 'llm').map((a) => a.role)
  return roles.includes('Custom') ? roles : [...roles, 'Custom']
}

/** The system prompt a new child agent with this role starts with. */
export function agentSystemPrompt(role: string, c: AgentCatalog = catalog): string {
  return c.agents.find((a) => a.role === role && a.system_prompt)?.system_prompt
    ?? `You are a specialist ${role}. Complete the task delegated by the master agent.`
}

/** The spec a tool-backed built-in drops as: its child settings, a tool node per need (the tool the
 *  workspace has, from the tool catalog) and a skill node per skill. */
export function builtinAgentSpec(agent: BuiltinAgent, toolItems: Map<string, ToolCatalogItem>): SavedAgentSpec {
  return {
    child: { role: agent.role, system_prompt: agent.system_prompt, kind: agent.kind, ...agent.extra },
    // One tool node per tool: two needs met by the same tool (Jira finds issues and duplicates) share it
    tools: agent.tools.filter((n) => !n.optional || n.installed)
      .filter((n, i, all) => all.findIndex((m) => m.use === n.use) === i).map((n) => {
      const item = toolItems.get(n.use)
      return {
        type: 'tool' as const,
        data: item
          ? { label: item.name, toolId: item.id, toolType: item.type, icon: item.icon, description: item.description,
              config: { ...item.default_config } }
          : { label: n.use, toolId: n.use, toolType: 'tool', icon: '🔧', description: n.why, config: {} },
      }
    }),
    skills: agent.skills.map((id) => ({ skill_id: id, label: id })),
  }
}

export async function setAgentsInstalled(agentIds: string[], installed: boolean, withTools = false):
    Promise<{ agents: BuiltinAgent[]; tools_installed: string[] }> {
  const res = await fetch(`${API_BASE}/api/agent-catalog/packages`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agent_ids: agentIds, installed, with_tools: withTools }),
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : `HTTP ${res.status}`)
  await refreshAgentCatalog()
  return body
}

export async function resetAgentPackages(): Promise<void> {
  const res = await fetch(`${API_BASE}/api/agent-catalog/packages`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  await refreshAgentCatalog()
}

/** Copy a built-in agent's eval set into a new eval dataset linked to ``appId``. */
export async function createAgentEvalDataset(agentId: string, appId?: string):
    Promise<{ dataset_id: string; name: string; cases_created: number; scorer: string }> {
  const res = await fetch(`${API_BASE}/api/agent-catalog/${encodeURIComponent(agentId)}/eval-dataset`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ app_id: appId ?? null }),
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : `HTTP ${res.status}`)
  return body
}
