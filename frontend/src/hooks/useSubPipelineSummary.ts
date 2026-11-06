import { useEffect, useMemo, useState } from 'react'
import { API_BASE } from '../types'
import type { ChildAgentNodeData, FlowNode } from '../types'

export interface SubPipelineSummary {
  models: { provider: string; model: string; sources: string[] }[]
  tools: { name: string; source: string }[]
  memory: boolean
  cache: boolean
  pipelines: { app_id: string; name: string; version: number; depth: number; called_from: string }[]
  errors: string[]
}

/**
 * What the published pipelines called from this canvas use (models, tools, memory, cache),
 * followed recursively at their pinned versions. Null when the canvas calls no pipeline.
 */
export function useSubPipelineSummary(nodes: FlowNode[], appId?: string): SubPipelineSummary | null {
  // Only the pipeline references matter — refetch when one is added, removed or re-pinned.
  const refs = useMemo(() => nodes
    .filter((n) => n.type === 'child_agent' && (n.data as ChildAgentNodeData).kind === 'pipeline')
    .map((n) => {
      const d = n.data as ChildAgentNodeData
      return { id: n.id, app_id: d.app_id ?? '', app_version: d.app_version ?? 0, app_name: d.app_name ?? '' }
    })
    .filter((r) => r.app_id), [nodes])
  const key = JSON.stringify(refs)
  const [summary, setSummary] = useState<SubPipelineSummary | null>(null)

  useEffect(() => {
    const parsed: typeof refs = JSON.parse(key)
    if (!parsed.length) { setSummary(null); return }
    let cancelled = false
    const flow = {
      nodes: parsed.map((r) => ({
        id: r.id, type: 'child_agent',
        data: { kind: 'pipeline', app_id: r.app_id, app_version: r.app_version, app_name: r.app_name },
      })),
      edges: [],
    }
    const t = setTimeout(() => {
      fetch(`${API_BASE}/api/pipelines/summary`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ flow_data: flow, app_id: appId ?? '' }),
      })
        .then((r) => (r.ok ? r.json() : null))
        .then((s) => { if (!cancelled) setSummary(s) })
        .catch(() => { if (!cancelled) setSummary(null) })
    }, 250)
    return () => { cancelled = true; clearTimeout(t) }
  }, [key, appId])

  return summary
}
