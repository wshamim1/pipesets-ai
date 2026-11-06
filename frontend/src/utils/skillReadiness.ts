import type { FlowEdge, FlowNode } from '../types'
import { requiredConfigFor } from './toolCatalog'

/** What a Skill node wired to an LLM node still needs before its skill can work (backend
 *  services/skills_runtime.readiness, which also refuses to publish such a flow). */
export interface SkillIssue {
  skillNodeId: string
  skill: string
  llmNodeId: string
  missingTools: string[]
  unconfigured: { nodeId: string; label: string; keys: string[] }[]
}

const neighbours = (id: string, edges: FlowEdge[]) =>
  new Set(edges.flatMap((e) => (e.source === id ? [e.target] : e.target === id ? [e.source] : [])))

/** The tools a Skill node's skill needs: the library's list (injected as ``requiredTools``), else its own copy. */
export function skillTools(node: FlowNode): string[] {
  const d = node.data as { requiredTools?: string[]; tool_ids?: string[] }
  return d.requiredTools ?? d.tool_ids ?? []
}

export function skillReadiness(
  nodes: FlowNode[], edges: FlowEdge[],
  requiredConfig: (toolId: string) => string[] = requiredConfigFor,
  onlySkillNodeId?: string,
): SkillIssue[] {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const issues: SkillIssue[] = []
  for (const skill of nodes.filter((n) => n.type === 'skill' && (!onlySkillNodeId || n.id === onlySkillNodeId))) {
    const required = skillTools(skill)
    if (!required.length) continue
    for (const llmId of neighbours(skill.id, edges)) {
      if (byId.get(llmId)?.type !== 'llm') continue
      const attached = new Map<string, FlowNode>()
      for (const id of neighbours(llmId, edges)) {
        const n = byId.get(id)
        const toolId = (n?.data as { toolId?: string } | undefined)?.toolId
        if (n?.type === 'tool' && toolId && !attached.has(toolId)) attached.set(toolId, n)
      }
      const missingTools = required.filter((t) => !attached.has(t))
      const unconfigured = required.flatMap((t) => {
        const tool = attached.get(t)
        if (!tool) return []
        // Settings from a linked Connection node are merged in when the tool runs
        if ([...neighbours(tool.id, edges)].some((id) => byId.get(id)?.type === 'connection')) return []
        const cfg = ((tool.data as { config?: Record<string, unknown> }).config) ?? {}
        const keys = requiredConfig(t).filter((k) => !String(cfg[k] ?? '').trim())
        return keys.length ? [{ nodeId: tool.id, label: String((tool.data as { label?: string }).label ?? t), keys }] : []
      })
      if (missingTools.length || unconfigured.length) {
        issues.push({ skillNodeId: skill.id, skill: String((skill.data as { label?: string }).label ?? 'Skill'),
          llmNodeId: llmId, missingTools, unconfigured })
      }
    }
  }
  return issues
}

export function describeSkillIssue(i: SkillIssue): string {
  return [
    ...(i.missingTools.length ? [`attach ${i.missingTools.join(', ')}`] : []),
    ...i.unconfigured.map((u) => `set ${u.keys.join(', ')} on ${u.label}`),
  ].join('; ')
}
