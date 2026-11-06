import { useState, useCallback } from 'react'
import { API_BASE } from '../types'
import type { AppRecord, FlowNode, FlowEdge, ConnectionNodeData } from '../types'
import { refreshPublishedApps } from '../utils/publishedApps'
import { describeGateResult } from '../components/PublishGateCard'
import type { GateResult } from '../components/PublishGateCard'

/** The server's reason for refusing a save (e.g. a key typed in plain text), else `fallback`. */
async function saveErrorMessage(res: Response, fallback: string): Promise<string> {
  const detail = (await res.json().catch(() => ({}))).detail
  if (typeof detail === 'string') return detail
  return typeof detail?.message === 'string' ? detail.message : fallback
}

export function useAppManager(
  loadFlow: (app: AppRecord) => void,
  nodes: FlowNode[],
  edges: FlowEdge[],
  setNodes: React.Dispatch<React.SetStateAction<FlowNode[]>>,
  setEdges: React.Dispatch<React.SetStateAction<FlowEdge[]>>,
  setSelectedNodeId: React.Dispatch<React.SetStateAction<string | null>>,
  /** Browser-held provider keys, for the eval gate's run on publish */
  getProviderKeys: () => Record<string, string> = () => ({}),
) {
  const [currentApp, setCurrentApp] = useState<AppRecord | null>(null)
  const [savedAppsList, setSavedAppsList] = useState<AppRecord[]>([])
  const [appSaveStatus, setAppSaveStatus] = useState('')

  const loadApp = useCallback(async (app: AppRecord) => {
    setCurrentApp(app)

    // ── Refresh connection node status/config from live API on load ──────────
    // Connection nodes store their config (host/user/pass) in the canvas node data.
    // On load, refresh them from /api/connections so status and label are current.
    // Credentials are NOT written into tool nodes — the PromptRunner resolves
    // them at runtime directly from the linked connection node.
    try {
      const res = await fetch(`${API_BASE}/api/connections`)
      if (res.ok) {
        const liveConns: Array<{ id: string; config: Record<string, any>; status: string; status_msg: string }> = await res.json()
        const connMap = new Map(liveConns.map((c) => [c.id, c]))

        const savedNodes: FlowNode[] = app.flow_data?.nodes ?? []
        const savedEdges: FlowEdge[] = app.flow_data?.edges ?? []

        const refreshedNodes = savedNodes.map((node) => {
          if (node.type !== 'connection') return node
          const connData = node.data as ConnectionNodeData
          const live = connMap.get(connData.connection_id)
          if (!live) return node
          return {
            ...node,
            data: {
              ...connData,
              config: { ...live.config },
              status: live.status as ConnectionNodeData['status'],
              status_msg: live.status_msg,
            },
          }
        })

        loadFlow({ ...app, flow_data: { ...app.flow_data, nodes: refreshedNodes, edges: savedEdges } })
        return
      }
    } catch {
      // API unavailable — load as-is
    }

    loadFlow(app)
  }, [loadFlow])

  const createApp = useCallback(async (name: string, description: string, flowData?: AppRecord['flow_data']) => {
    const initialFlow = flowData ?? { nodes: [], edges: [] }
    try {
      const res = await fetch(`${API_BASE}/api/apps`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), description: description.trim(), flow_data: initialFlow }),
      })
      if (res.ok) {
        const created: AppRecord = await res.json()
        setSavedAppsList((prev) => [created, ...prev])
        setCurrentApp(created)
        setNodes(created.flow_data?.nodes ?? initialFlow.nodes ?? [])
        setEdges(created.flow_data?.edges ?? initialFlow.edges ?? [])
        setSelectedNodeId((created.flow_data?.nodes ?? initialFlow.nodes ?? [])[0]?.id ?? null)
        return created
      }
    } catch {
      const fallback: AppRecord = {
        id: `local-${Date.now()}`,
        name: name.trim(),
        description: description.trim(),
        flow_data: initialFlow,
        status: 'draft',
        version: 0,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }
      setSavedAppsList((prev) => [fallback, ...prev])
      setCurrentApp(fallback)
      setNodes(fallback.flow_data?.nodes ?? [])
      setEdges(fallback.flow_data?.edges ?? [])
      setSelectedNodeId((fallback.flow_data?.nodes ?? [])[0]?.id ?? null)
      return fallback
    }
    return null
  }, [setNodes, setEdges, setSelectedNodeId])

  const saveCurrentApp = useCallback(async () => {
    if (!currentApp) return
    setAppSaveStatus('Saving to SQLite...')
    try {
      const res = await fetch(`${API_BASE}/api/apps/${currentApp.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: currentApp.name, description: currentApp.description, flow_data: { nodes, edges } }),
      })
      if (res.ok) {
        const updated = await res.json()
        setCurrentApp(updated)
        setSavedAppsList((prev) => prev.map((a) => (a.id === updated.id ? updated : a)))
        setAppSaveStatus('✓ Saved to SQLite')
        setTimeout(() => setAppSaveStatus(''), 2500)
      } else {
        setAppSaveStatus(`✗ ${await saveErrorMessage(res, 'Error saving app')}`)
        setTimeout(() => setAppSaveStatus(''), 8000)
      }
    } catch {
      setAppSaveStatus('Offline (Saved in memory)')
      setTimeout(() => setAppSaveStatus(''), 2500)
    }
  }, [currentApp, nodes, edges])

  const publishApp = useCallback(async () => {
    if (!currentApp) return
    setAppSaveStatus('Publishing...')
    try {
      // First save the latest flow, then publish
      const saveRes = await fetch(`${API_BASE}/api/apps/${currentApp.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: currentApp.name, description: currentApp.description, flow_data: { nodes, edges } }),
      })
      if (!saveRes.ok) {
        setAppSaveStatus(`✗ ${await saveErrorMessage(saveRes, 'Error saving before publish')}`)
        setTimeout(() => setAppSaveStatus(''), 8000)
        return
      }
      const publish = (force: boolean) => fetch(`${API_BASE}/api/apps/${currentApp.id}/publish`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force, provider_keys: getProviderKeys() }),
      })
      setAppSaveStatus('Publishing… (running eval gate if set)')
      let publishRes = await publish(false)
      if (publishRes.status === 409) {
        // Eval gate failed (or couldn't run) — show why and offer to override
        const detail = (await publishRes.json().catch(() => ({}))).detail ?? {}
        if (detail.skills) {   // a skill's tools aren't attached or set up: fix first, no override
          setAppSaveStatus(`✗ ${detail.message}`)
          setTimeout(() => setAppSaveStatus(''), 10000)
          return
        }
        const gate: GateResult | undefined = detail.gate
        const summary = gate ? `${describeGateResult(gate)}\n\n${gate.reasons.join('\n')}` : String(detail.message ?? '')
        if (!gate || gate.status === 'error' || !window.confirm(`Eval gate failed\n\n${summary}\n\nPublish anyway? The version will be marked as overridden.`)) {
          setAppSaveStatus(gate?.status === 'error' ? `✗ ${detail.message}` : '✗ Publish blocked by eval gate')
          setTimeout(() => setAppSaveStatus(''), 6000)
          return
        }
        setAppSaveStatus('Publishing (override)…')
        publishRes = await publish(true)
      }
      if (publishRes.ok) {
        const updated: AppRecord & { publish_gate?: GateResult | null } = await publishRes.json()
        setCurrentApp(updated)
        setSavedAppsList((prev) => prev.map((a) => (a.id === updated.id ? updated : a)))
        refreshPublishedApps()
        const g = updated.publish_gate
        const gateNote = !g ? ''
          : g.status === 'passed' ? ` · eval ${describeGateResult(g)}`
          : g.status === 'warned' ? ` · ⚠ eval gate failed (${describeGateResult(g)})`
          : ' · eval gate overridden'
        setAppSaveStatus(`✓ Published v${updated.version}${gateNote}`)
        setTimeout(() => setAppSaveStatus(''), g && g.status !== 'passed' ? 8000 : 4000)
      } else {
        setAppSaveStatus('Publish failed')
      }
    } catch {
      setAppSaveStatus('Offline – could not publish')
      setTimeout(() => setAppSaveStatus(''), 2500)
    }
  }, [currentApp, nodes, edges, getProviderKeys])

  const startEditing = useCallback(async () => {
    if (!currentApp) return
    try {
      const res = await fetch(`${API_BASE}/api/apps/${currentApp.id}/edit`, { method: 'POST' })
      if (res.ok) {
        const updated: AppRecord = await res.json()
        setCurrentApp(updated)
        setSavedAppsList((prev) => prev.map((a) => (a.id === updated.id ? updated : a)))
        setAppSaveStatus(`Editing v${updated.version + 1}-draft`)
        setTimeout(() => setAppSaveStatus(''), 2500)
      }
    } catch { /* ignore */ }
  }, [currentApp])

  const deleteApp = useCallback(async (appId: string) => {
    try {
      await fetch(`${API_BASE}/api/apps/${appId}`, { method: 'DELETE' })
    } catch { /* ignore */ }
    const updated = savedAppsList.filter((a) => a.id !== appId)
    setSavedAppsList(updated)
    if (currentApp?.id === appId) {
      if (updated.length > 0) {
        loadApp(updated[0])
      } else {
        setCurrentApp(null)
        setNodes([])
        setEdges([])
      }
    }
    return updated
  }, [savedAppsList, currentApp, loadApp, setNodes, setEdges])

  return {
    currentApp, setCurrentApp,
    savedAppsList, setSavedAppsList,
    appSaveStatus,
    loadApp,
    createApp,
    saveCurrentApp,
    publishApp,
    startEditing,
    deleteApp,
  }
}
