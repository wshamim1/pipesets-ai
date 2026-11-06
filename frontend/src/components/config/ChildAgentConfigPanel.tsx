import { useEffect, useState } from 'react'
import { API_BASE } from '../../types'
import type { ChildAgentNodeData, FlowEdge, FlowNode } from '../../types'
import { fetchAppVersions, usePublishedApps } from '../../utils/publishedApps'
import type { AppVersionInfo } from '../../utils/publishedApps'
import { openPipelinePreview } from '../../utils/pipelinePreview'
import { agentRoles, agentSystemPrompt, createAgentEvalDataset, useAgentCatalog } from '../../utils/agentCatalog'
import { ApiKeyField } from './ApiKeyField'
import { buildAgentSpec, deleteSavedAgent, saveAgent, updateSavedAgent, useSavedAgents } from '../../utils/savedAgents'

interface Props {
  activeNode: FlowNode
  onUpdate: (nodeId: string, fields: Record<string, any>) => void
  onDelete: (nodeId: string) => void
  onSave: () => void
  readOnly?: boolean
  /** Id of the app being edited — excluded from the pipeline picker (no self-reference). */
  currentAppId?: string
  /** The canvas, so "Save as agent" can include the tool and skill nodes wired to this child */
  nodes?: FlowNode[]
  edges?: FlowEdge[]
}

const PROVIDERS = [
  { id: 'openai', label: 'OpenAI', models: ['gpt-5.5', 'gpt-5.4-mini', 'gpt-4.1', 'gpt-4o'] },
  { id: 'anthropic', label: 'Anthropic', models: ['claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5'] },
  { id: 'groq', label: 'Groq', models: ['openai/gpt-oss-120b', 'openai/gpt-oss-20b'] },
  { id: 'gemini', label: 'Google Gemini', models: ['gemini-3.5-flash', 'gemini-2.5-pro'] },
  { id: 'ollama', label: 'Ollama (Local)', models: ['llama3.2', 'llama3.1', 'mistral'] },
  { id: 'llamacpp', label: 'llama.cpp (Local)', models: ['default'] },
  { id: 'mock', label: 'Mock / Simulator', models: ['mock-gpt-4', 'mock-claude'] },
]

const PROTOCOLS = [
  { id: 'openai', label: 'OpenAI-compatible (/v1/chat/completions)' },
  { id: 'rest', label: 'Generic REST / webhook' },
  { id: 'a2a', label: 'A2A (Agent2Agent JSON-RPC)' },
] as const

export function ChildAgentConfigPanel({ activeNode, onUpdate, onDelete, onSave, readOnly, currentAppId, nodes = [], edges = [] }: Props) {
  const data = activeNode.data as ChildAgentNodeData
  const providerModels = PROVIDERS.find((p) => p.id === data.provider)?.models ?? []
  const isExternal = data.kind === 'external'
  const isPipeline = data.kind === 'pipeline'
  const { apps: allPublished, loading: appsLoading } = usePublishedApps()
  const publishedApps = allPublished.filter((a) => a.id !== currentAppId)
  const [versions, setVersions] = useState<AppVersionInfo[]>([])
  const [versionsLoading, setVersionsLoading] = useState(false)
  const [versionsError, setVersionsError] = useState(false)

  useEffect(() => {
    if (!isPipeline || !data.app_id) { setVersions([]); return }
    let cancelled = false
    setVersionsLoading(true)
    setVersionsError(false)
    fetchAppVersions(data.app_id)
      .then((v) => { if (!cancelled) setVersions(v) })
      .catch(() => { if (!cancelled) { setVersions([]); setVersionsError(true) } })
      .finally(() => { if (!cancelled) setVersionsLoading(false) })
    return () => { cancelled = true }
  }, [isPipeline, data.app_id])

  const selectedApp = publishedApps.find((a) => a.id === data.app_id)
  const latestVersion = versions[0]?.version ?? selectedApp?.version ?? 0
  const pinnedVersion = data.app_version ?? 0
  const pinned = versions.find((v) => v.version === pinnedVersion)
  const pinnedMissing = !!data.app_id && pinnedVersion > 0 && !versionsLoading && !versionsError && !pinned
  const upgradeAvailable = pinnedVersion > 0 && latestVersion > pinnedVersion
  // Nearest saved version below the pinned one — the one-click rollback target.
  const previousVersion = pinnedVersion > 0 ? versions.find((v) => v.version < pinnedVersion)?.version : undefined
  const oldestSaved = versions[versions.length - 1]?.version
  const protocol = data.protocol ?? 'openai'
  const authType = data.auth_type ?? 'bearer'
  const [testing, setTesting] = useState(false)
  const savedAgents = useSavedAgents()
  const agentCatalog = useAgentCatalog()
  const roles = agentRoles(agentCatalog)
  const builtin = agentCatalog.agents.find((a) => a.id === data.builtin_agent_id)
  const [evalResult, setEvalResult] = useState<{ ok: boolean; text: string } | null>(null)

  const createEvalSet = async () => {
    if (!builtin) return
    setEvalResult(null)
    try {
      const ds = await createAgentEvalDataset(builtin.id, currentAppId)
      setEvalResult({ ok: true, text: `Created “${ds.name}” with ${ds.cases_created} cases. Run it from Evaluate with the LLM judge scorer.` })
    } catch (e: any) {
      setEvalResult({ ok: false, text: e?.message || 'Could not create the eval dataset' })
    }
  }
  const savedFrom = savedAgents.find((a) => a.id === data.saved_agent_id)
  const [agentName, setAgentName] = useState('')
  const [agentBusy, setAgentBusy] = useState(false)
  const [agentResult, setAgentResult] = useState<{ ok: boolean; text: string } | null>(null)

  /** Save this child and its wired tool / skill nodes as a reusable agent (or a new version of the one it came from). */
  const saveAsAgent = async (asNew: boolean) => {
    setAgentBusy(true)
    setAgentResult(null)
    try {
      const spec = buildAgentSpec(activeNode, nodes, edges)
      const name = (agentName || data.label).trim() || 'My agent'
      const saved = savedFrom && !asNew
        ? await updateSavedAgent(savedFrom.id, { spec })
        : await saveAgent({ name, spec })
      onUpdate(activeNode.id, { saved_agent_id: saved.id, saved_agent_version: saved.version })
      const wired = `${spec.tools.length} tool${spec.tools.length === 1 ? '' : 's'}, ${spec.skills.length} skill${spec.skills.length === 1 ? '' : 's'}`
      const keys = saved.stripped?.length ? ` Keys and passwords weren't saved (${saved.stripped.length}); set them again after dropping it.` : ''
      setAgentResult({ ok: true, text: `Saved “${saved.name}” v${saved.version} with ${wired}. Find it under Agents → Saved agents.${keys}` })
    } catch (e: any) {
      setAgentResult({ ok: false, text: e?.message || 'Could not save the agent' })
    } finally {
      setAgentBusy(false)
    }
  }
  const [testResult, setTestResult] = useState<{ ok: boolean; text: string } | null>(null)

  const testConnection = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const res = await fetch(`${API_BASE}/api/agents/external/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          endpoint_url: data.endpoint_url ?? '',
          protocol,
          api_key: data.api_key,
          auth_type: authType,
          auth_header: data.auth_header || 'X-API-Key',
          model: data.model,
          request_template: data.request_template ?? '',
          response_path: data.response_path ?? '',
        }),
      })
      if (!res.ok) {
        setTestResult({ ok: false, text: await res.text().catch(() => res.statusText) })
      } else {
        const r = await res.json()
        setTestResult({ ok: r.ok, text: `${r.latency_ms} ms — ${r.output}` })
      }
    } catch (err) {
      setTestResult({ ok: false, text: String(err) })
    } finally {
      setTesting(false)
    }
  }

  const handleToolIdInput = (raw: string) => {
    const ids = raw.split(',').map((s) => s.trim()).filter(Boolean)
    onUpdate(activeNode.id, { allowed_tool_ids: ids })
  }

  return (
    <div className="bottom-config-grid">
      {/* Card 1 — Identity & Role */}
      <div className="config-card">
        <h4 className="card-heading">1. Identity &amp; Role</h4>
        <div className="form-group">
          <label className="field-label">Node Label</label>
          <input
            type="text"
            className="field-input"
            value={data.label}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { label: e.target.value })}
          />
        </div>
        <div className="form-group">
          <label className="field-label">Specialist Role</label>
          <select
            className="field-select"
            value={roles.includes(data.role) ? data.role : 'Custom'}
            disabled={readOnly}
            onChange={(e) => {
              const role = e.target.value
              if (role === 'Custom') return
              // Swap the prompt too, unless the user has already edited the old role's default
              const keepPrompt = data.system_prompt && data.system_prompt !== agentSystemPrompt(data.role, agentCatalog)
              onUpdate(activeNode.id, keepPrompt ? { role } : { role, system_prompt: agentSystemPrompt(role, agentCatalog) })
            }}
          >
            {roles.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
        <div className="form-group">
          <label className="field-label">Custom Role Name</label>
          <input
            type="text"
            className="field-input"
            placeholder="e.g. Legal Reviewer"
            value={data.role}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { role: e.target.value })}
          />
          <span className="field-hint">The master agent uses this role label to decide when to delegate to this child.</span>
        </div>
      </div>

      {/* Card 2 — Published pipeline */}
      {isPipeline && (
        <div className="config-card">
          <h4 className="card-heading">2. Published Pipeline</h4>
          <div className="form-group">
            <label className="field-label">Pipeline</label>
            <select
              className="field-select"
              value={data.app_id ?? ''}
              disabled={readOnly || appsLoading}
              onChange={(e) => {
                const app = publishedApps.find((a) => a.id === e.target.value)
                onUpdate(activeNode.id, {
                  app_id: e.target.value,
                  app_name: app?.name ?? '',
                  app_version: app?.version ?? 0,
                  ...(app && (!data.label || data.label === 'Pipeline Agent') ? { label: app.name } : {}),
                })
              }}
            >
              <option value="">{appsLoading && !publishedApps.length ? 'Loading…' : 'Select a published pipeline'}</option>
              {data.app_id && !selectedApp && !appsLoading && (
                <option value={data.app_id}>{data.app_name || data.app_id} (unavailable)</option>
              )}
              {publishedApps.map((a) => <option key={a.id} value={a.id}>{a.name} — latest v{a.version}</option>)}
            </select>
          </div>
          {data.app_id && (
            <div className="form-group">
              <label className="field-label">Version</label>
              <select
                className="field-select"
                value={pinnedVersion}
                disabled={readOnly || versionsLoading}
                onChange={(e) => onUpdate(activeNode.id, { app_version: Number(e.target.value) })}
              >
                {pinnedVersion === 0 && <option value={0}>Always latest (legacy — pick a version to pin)</option>}
                {pinnedMissing && <option value={pinnedVersion}>v{pinnedVersion} (unavailable)</option>}
                {versionsError && pinnedVersion > 0 && <option value={pinnedVersion}>v{pinnedVersion}</option>}
                {versions.map((v) => (
                  <option key={v.version} value={v.version}>
                    v{v.version}{v.version === latestVersion ? ' (latest)' : ''} · {new Date(v.created_at).toLocaleDateString()}
                  </option>
                ))}
              </select>
              <span className="field-hint">
                The child stays pinned to this version. Publishing the pipeline again never changes it — pick any
                version here to upgrade or roll back.
              </span>
              {pinned && (
                <span className="field-hint">
                  {pinned.description || 'No description'} · {pinned.node_count} nodes · v{pinned.version}
                  {' · '}
                  <button
                    type="button"
                    className="link-btn"
                    onClick={() => openPipelinePreview({ appId: data.app_id!, version: pinned.version, name: data.app_name || data.label })}
                  >
                    View nodes
                  </button>
                </span>
              )}
              {upgradeAvailable && !pinnedMissing && (
                <div className="pipeline-upgrade-box">
                  <span>★ v{latestVersion} is available (pinned to v{pinnedVersion}).</span>
                  {!readOnly && (
                    <button
                      type="button"
                      className="save-btn"
                      onClick={() => onUpdate(activeNode.id, { app_version: latestVersion })}
                    >
                      Upgrade to v{latestVersion}
                    </button>
                  )}
                </div>
              )}
              {previousVersion != null && !readOnly && (
                <button
                  type="button"
                  className="pipeline-rollback-btn"
                  onClick={() => onUpdate(activeNode.id, { app_version: previousVersion })}
                >
                  ↩ Roll back to v{previousVersion}
                </button>
              )}
              {!versionsError && oldestSaved != null && oldestSaved > 1 && (
                <span className="field-hint">
                  Versions before v{oldestSaved} were published before version history existed and can't be restored.
                  Every publish from now on can be rolled back to.
                </span>
              )}
              {versionsError && (
                <span className="field-hint" style={{ color: '#b91c1c' }}>
                  Couldn't load version history — make sure the backend is up to date (restart it), then reopen this node.
                </span>
              )}
              {pinnedMissing && (
                <span className="field-hint" style={{ color: '#b91c1c' }}>
                  v{pinnedVersion} was published before version history existed and can't be run. Pick an available version.
                </span>
              )}
            </div>
          )}
          {data.app_id && !selectedApp && !appsLoading && (
            <span className="field-hint" style={{ color: '#b91c1c' }}>
              This pipeline has no published version or was deleted — runs will fail until you pick another.
            </span>
          )}
          <div className="form-group">
            <label className="field-label">Timeout (ms)</label>
            <input
              type="number"
              className="field-input"
              min={1000}
              value={data.timeout_ms ?? 45000}
              disabled={readOnly}
              onChange={(e) => onUpdate(activeNode.id, { timeout_ms: Number(e.target.value) || 45000 })}
            />
          </div>
        </div>
      )}

      {/* Card 2 — External endpoint */}
      {isExternal && (
        <div className="config-card">
          <h4 className="card-heading">2. External Agent Endpoint</h4>
          <div className="form-group">
            <label className="field-label">Protocol</label>
            <select
              className="field-select"
              value={protocol}
              disabled={readOnly}
              onChange={(e) => onUpdate(activeNode.id, { protocol: e.target.value })}
            >
              {PROTOCOLS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
          </div>
          <div className="form-group">
            <label className="field-label">Endpoint URL</label>
            <input
              type="text"
              className="field-input code-font"
              placeholder={protocol === 'openai' ? 'https://host/v1' : 'https://host/agent'}
              value={data.endpoint_url ?? ''}
              disabled={readOnly}
              onChange={(e) => onUpdate(activeNode.id, { endpoint_url: e.target.value })}
            />
            <span className="field-hint">Private / loopback hosts are blocked unless allowed on the backend.</span>
          </div>
          {protocol === 'openai' && (
            <div className="form-group">
              <label className="field-label">Model</label>
              <input
                type="text"
                className="field-input code-font"
                placeholder="model name expected by the remote agent"
                value={data.model}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { model: e.target.value })}
              />
            </div>
          )}
          <div className="form-group">
            <label className="field-label">Auth</label>
            <select
              className="field-select"
              value={authType}
              disabled={readOnly}
              onChange={(e) => onUpdate(activeNode.id, { auth_type: e.target.value })}
            >
              <option value="none">None</option>
              <option value="bearer">Bearer token</option>
              <option value="header">Custom header</option>
            </select>
          </div>
          {authType === 'header' && (
            <div className="form-group">
              <label className="field-label">Header Name</label>
              <input
                type="text"
                className="field-input code-font"
                value={data.auth_header ?? 'X-API-Key'}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { auth_header: e.target.value })}
              />
            </div>
          )}
          {authType !== 'none' && (
            <div className="form-group">
              <label className="field-label">Token / API Key</label>
              <ApiKeyField provider="" kind="tool" value={data.api_key} readOnly={readOnly} secretName={`${data.label} token`}
                onChange={(v) => onUpdate(activeNode.id, { api_key: v })} />
            </div>
          )}
          {protocol === 'rest' && (
            <>
              <div className="form-group">
                <label className="field-label">Request Body (JSON)</label>
                <textarea
                  rows={3}
                  className="field-textarea code-font"
                  placeholder={'{"task": "{{task}}", "context": "{{context}}"}'}
                  value={data.request_template ?? ''}
                  disabled={readOnly}
                  onChange={(e) => onUpdate(activeNode.id, { request_template: e.target.value })}
                />
                <span className="field-hint">Use {'{{task}}'} and {'{{context}}'} placeholders.</span>
              </div>
              <div className="form-group">
                <label className="field-label">Response Path</label>
                <input
                  type="text"
                  className="field-input code-font"
                  placeholder="e.g. data.0.text (blank = raw body)"
                  value={data.response_path ?? ''}
                  disabled={readOnly}
                  onChange={(e) => onUpdate(activeNode.id, { response_path: e.target.value })}
                />
              </div>
            </>
          )}
          <button
            type="button"
            className="save-btn"
            disabled={testing || !data.endpoint_url}
            onClick={testConnection}
          >
            {testing ? 'Testing…' : 'Test connection'}
          </button>
          {testResult && (
            <span className="field-hint" style={{ color: testResult.ok ? '#166534' : '#b91c1c' }}>
              {testResult.ok ? '✓ ' : '✗ '}{testResult.text}
            </span>
          )}
        </div>
      )}

      {/* Card 2 — LLM */}
      {!isExternal && !isPipeline && (
      <div className="config-card">
        <h4 className="card-heading">2. LLM</h4>
        <div className="form-group">
          <label className="field-label">Provider</label>
          <select
            className="field-select"
            value={data.provider}
            disabled={readOnly}
            onChange={(e) => {
              const prov = PROVIDERS.find((p) => p.id === e.target.value)
              onUpdate(activeNode.id, { provider: e.target.value, model: prov?.models[0] ?? '' })
            }}
          >
            {PROVIDERS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
          <span className="field-hint">Child agents can use a different (cheaper/faster) model than the master.</span>
        </div>
        <div className="form-group">
          <label className="field-label">Model</label>
          <select
            className="field-select"
            value={data.model}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { model: e.target.value })}
          >
            {providerModels.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
        <div className="form-group">
          <label className="field-label">API Key</label>
          <ApiKeyField provider={data.provider} value={data.api_key} readOnly={readOnly}
            emptyLabel="— Share the master agent's key —"
            onChange={(v) => onUpdate(activeNode.id, { api_key: v })} />
        </div>
      </div>
      )}

      {/* Card 3 — System Prompt & Tools */}
      {!isPipeline && (!isExternal || protocol === 'openai') && (
      <div className="config-card">
        <h4 className="card-heading">3. System Prompt{isExternal ? '' : ' & Tools'}</h4>
        <div className="form-group">
          <label className="field-label">System Prompt</label>
          <textarea
            rows={4}
            className="field-textarea"
            placeholder="You are a specialist researcher. Given a task from the master agent, find accurate information and return a concise summary with sources."
            value={data.system_prompt}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { system_prompt: e.target.value })}
          />
          <span className="field-hint">This agent only follows this prompt. The master's goal is injected as the user message.</span>
        </div>
        {!isExternal && (
        <div className="form-group">
          <label className="field-label">Allowed Tool IDs (comma-separated)</label>
          <input
            type="text"
            className="field-input code-font"
            placeholder="web_search, python_interpreter"
            value={(data.allowed_tool_ids ?? []).join(', ')}
            disabled={readOnly}
            onChange={(e) => handleToolIdInput(e.target.value)}
          />
          <span className="field-hint">Wire Tool, MCP or Skill nodes to this agent and it calls them while doing its task. These ids are only used when no tool node is wired.</span>
        </div>
        )}
      </div>
      )}

      {/* Card 4 — Actions */}
      <div className="config-card">
        <h4 className="card-heading">4. Node Actions</h4>
        <div className="tool-status-box ca-status-box">
          <span className="status-dot ca-dot" />
          <span>
            {isPipeline
              ? 'Pipeline agent — runs a published pipeline for the Master Agent'
              : isExternal
                ? 'External agent — called over HTTP by the Master Agent'
                : 'Specialist child — receives tasks from the Master Agent'}
          </span>
        </div>
        <div className="agent-wiring-hint">
          <p className="field-hint">
            <strong>How to wire:</strong> Connect this node's output handle to the Master Agent node. The master will
            call this child when it needs <em>{data.role || 'this role'}</em> work done.
          </p>
        </div>
        {!readOnly && (
          <div className="card-actions-row">
            <button type="button" className="save-btn" onClick={onSave}>Save to App</button>
            <button type="button" className="delete-btn" onClick={() => onDelete(activeNode.id)}>Delete Node</button>
          </div>
        )}
      </div>

      {/* Card 5 — Reuse */}
      {!readOnly && (
      <div className="config-card">
        <h4 className="card-heading">5. Reuse This Agent</h4>
        <p className="field-hint">
          Saves this agent with the tool and skill nodes wired to it, so you can drop it into other pipelines.
          Keys and passwords are not saved.
        </p>
        {savedFrom ? (
          <>
            <p className="field-hint">From saved agent <strong>{savedFrom.name}</strong> (v{data.saved_agent_version ?? savedFrom.version}; latest v{savedFrom.version}).</p>
            <div className="card-actions-row">
              <button type="button" className="save-btn" disabled={agentBusy} onClick={() => saveAsAgent(false)}>
                {agentBusy ? 'Saving…' : `Update “${savedFrom.name}”`}
              </button>
              <button type="button" className="save-btn" disabled={agentBusy} onClick={() => saveAsAgent(true)}>Save as new agent</button>
              <button type="button" className="delete-btn" disabled={agentBusy} onClick={async () => {
                if (!window.confirm(`Delete the saved agent “${savedFrom.name}” and its versions? Pipelines that use it keep their copy.`)) return
                try {
                  await deleteSavedAgent(savedFrom.id)
                  onUpdate(activeNode.id, { saved_agent_id: undefined, saved_agent_version: undefined })
                  setAgentResult({ ok: true, text: `Deleted “${savedFrom.name}”.` })
                } catch (e: any) {
                  setAgentResult({ ok: false, text: e?.message || 'Could not delete the agent' })
                }
              }}>Delete saved agent</button>
            </div>
          </>
        ) : (
          <div className="form-group">
            <label className="field-label">Agent name</label>
            <input type="text" className="field-input" placeholder={data.label} value={agentName}
              onChange={(e) => setAgentName(e.target.value)} />
            <div className="card-actions-row">
              <button type="button" className="save-btn" disabled={agentBusy} onClick={() => saveAsAgent(true)}>
                {agentBusy ? 'Saving…' : 'Save as agent'}
              </button>
            </div>
          </div>
        )}
        {agentResult && (
          <span className="field-hint" role="status" style={{ color: agentResult.ok ? '#166534' : '#b91c1c' }}>{agentResult.text}</span>
        )}
        {builtin && builtin.eval_cases > 0 && (
          <div className="form-group">
            <label className="field-label">Eval set</label>
            <p className="field-hint">{builtin.name} comes with {builtin.eval_cases} test cases. Copy them into an eval dataset for this pipeline to measure it with your model.</p>
            <div className="card-actions-row">
              <button type="button" className="save-btn" onClick={createEvalSet}>Create eval dataset</button>
            </div>
            {evalResult && (
              <span className="field-hint" role="status" style={{ color: evalResult.ok ? '#166534' : '#b91c1c' }}>{evalResult.text}</span>
            )}
          </div>
        )}
      </div>
      )}
    </div>
  )
}
