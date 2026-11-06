import { useEffect, useMemo, useState } from 'react'
import type { AppRecord, FlowEdge, FlowNode, TraceRecord } from '../types'
import { API_BASE } from '../types'
import { useCredentials } from '../context/CredentialsContext'
import { validatePipeline } from '../utils/pipelineValidation'
import { useRequiredConfig } from '../utils/toolCatalog'
import { NodeIcon } from './NodeIcon'
import { PublishGateCard } from './PublishGateCard'

type CheckState = 'ok' | 'warn' | 'error'

interface Props {
  currentApp: AppRecord | null
  nodes: FlowNode[]
  edges: FlowEdge[]
  onFocusNode?: (nodeId: string) => void
  /** Open the Monitor → Traces view for the full run history */
  onOpenMonitor?: () => void
}

function getPipelineKind(nodes: FlowNode[]): string {
  const hasMaster = nodes.some((n) => n.type === 'master_agent')
  const hasRag = nodes.some((n) => n.type === 'doc_loader' || n.type === 'text_splitter' || n.type === 'embedding' || n.type === 'vector_store' || n.type === 'retriever')
  const hasLlm = nodes.some((n) => n.type === 'llm')
  const hasTools = nodes.some((n) => n.type === 'tool' || n.type === 'toolkit')

  if (hasMaster && hasRag) return 'Hybrid (Agent + RAG)'
  if (hasMaster) return 'Multi-Agent'
  if (hasRag) return 'RAG Pipeline'
  if (hasLlm && hasTools) return 'Tool-Enabled LLM'
  if (hasLlm) return 'Single LLM'
  return 'Empty Canvas'
}

function checkIcon(state: CheckState): string {
  if (state === 'ok') return '✓'
  if (state === 'warn') return '!'
  return '✕'
}

const NODE_LABELS: Record<string, string> = {
  llm: 'LLM',
  master_agent: 'Master',
  child_agent: 'Child',
  doc_loader: 'Loader',
  text_splitter: 'Splitter',
  embedding: 'Embedding',
  vector_store: 'Vector',
  retriever: 'Retriever',
  tool: 'Tool',
  toolkit: 'Toolkit',
  memory: 'Memory',
  cache: 'Cache',
  connection: 'Conn',
  knowledge_base: 'KB',
  gateway: 'Flow',
  wf_step: 'Step',
  output_parser: 'Parser',
  middleware: 'Guard',
  human_gate: 'Human gate',
  checkpointer: 'Checkpoint',
  reranker: 'Reranker',
  skill: 'Skill',
  start: 'Start',
  stop: 'Stop',
}

export function ActiveAppOverviewPanel({
  currentApp,
  nodes,
  edges,
  onFocusNode,
  onOpenMonitor,
}: Props) {
  const { resolveApiKey } = useCredentials()
  const requiredConfig = useRequiredConfig()
  const [latestTrace, setLatestTrace] = useState<TraceRecord | null>(null)
  const [recentTraces, setRecentTraces] = useState<TraceRecord[]>([])
  const [traceLoading, setTraceLoading] = useState(false)

  const nodeCounts = useMemo(() => {
    return nodes.reduce<Record<string, number>>((acc, n) => {
      acc[n.type] = (acc[n.type] ?? 0) + 1
      return acc
    }, {})
  }, [nodes])

  const pipelineKind = useMemo(() => getPipelineKind(nodes), [nodes])

  const validationIssues = useMemo(
    () => validatePipeline(nodes, edges, resolveApiKey, requiredConfig),
    [nodes, edges, resolveApiKey, requiredConfig],
  )
  const blockingCount = validationIssues.filter((i) => i.severity === 'error').length
  const warningCount = validationIssues.filter((i) => i.severity === 'warn').length

  useEffect(() => {
    if (!currentApp?.id) {
      setLatestTrace(null)
      return
    }
    let ignore = false
    setTraceLoading(true)
    fetch(`${API_BASE}/api/traces?app_id=${encodeURIComponent(currentApp.id)}&limit=20`)
      .then((r) => (r.ok ? r.json() : []))
      .then((rows: TraceRecord[]) => {
        if (ignore) return
        setRecentTraces(rows)
        setLatestTrace(rows[0] ?? null)
      })
      .catch(() => {
        if (!ignore) {
          setRecentTraces([])
          setLatestTrace(null)
        }
      })
      .finally(() => {
        if (!ignore) setTraceLoading(false)
      })

    return () => {
      ignore = true
    }
  }, [currentApp?.id])

  const recentReliability = useMemo(() => {
    const total = recentTraces.length
    if (total === 0) {
      return { total: 0, retryRuns: 0, fallbackRuns: 0, avgAttempts: 1, fallbackRate: 0 }
    }
    const retryRuns = recentTraces.filter((t) => (t.attempt_count ?? 1) > 1).length
    const fallbackRuns = recentTraces.filter((t) => Number(t.used_fallback) > 0).length
    const totalAttempts = recentTraces.reduce((sum, t) => sum + Math.max(1, Number(t.attempt_count) || 1), 0)
    return {
      total,
      retryRuns,
      fallbackRuns,
      avgAttempts: totalAttempts / total,
      fallbackRate: Math.round((fallbackRuns / total) * 100),
    }
  }, [recentTraces])

  if (!currentApp) {
    return (
      <div className="overview-panel-body">
        <div className="overview-empty">No app open. Pick one from the app menu above the canvas, or from Apps.</div>
      </div>
    )
  }

  const appUpdated = new Date(currentApp.updated_at).toLocaleString()
  const nodeCountEntries = Object.entries(nodeCounts).sort((a, b) => b[1] - a[1])
  const formatLatency = (ms: number) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`)
  const ranOk = latestTrace?.status === 'success' || latestTrace?.status === 'ok'

  return (
    <div className="overview-panel-body">
      {/* Readiness — the one thing to act on, so it comes first */}
      <section className="overview-card">
        <div className="overview-card-head">
          <h3 className="overview-title">Readiness</h3>
          {validationIssues.length > 0 && (
            <span className="overview-muted">
              {blockingCount > 0 && `${blockingCount} blocking`}
              {blockingCount > 0 && warningCount > 0 && ' · '}
              {warningCount > 0 && `${warningCount} warning${warningCount === 1 ? '' : 's'}`}
            </span>
          )}
        </div>
        {validationIssues.length === 0 ? (
          <div className="overview-ready">
            <span className="overview-check-icon">✓</span>
            <span>Ready to run</span>
          </div>
        ) : (
          <div className="overview-check-list">
            {validationIssues.map((check) => (
              <div key={check.id} className={`overview-check ${check.severity}`}>
                <div className="overview-check-head">
                  <span className="overview-check-icon">{checkIcon(check.severity)}</span>
                  <span className="overview-check-label">{check.title}</span>
                  {check.nodeId && onFocusNode && (
                    <button type="button" className="overview-fix-btn" onClick={() => onFocusNode(check.nodeId!)}>
                      Show
                    </button>
                  )}
                </div>
                <div className="overview-check-hint">{check.hint}</div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Last run — four numbers people check, details on demand */}
      <section className="overview-card">
        <div className="overview-card-head">
          <h3 className="overview-title">Last run</h3>
          {latestTrace && onOpenMonitor && (
            <button type="button" className="overview-link-btn" onClick={onOpenMonitor}>View in Monitor →</button>
          )}
        </div>
        {traceLoading ? (
          <div className="overview-muted">Loading…</div>
        ) : latestTrace ? (
          <>
            <div className="overview-stat-grid">
              <div className="overview-stat">
                <span className={`overview-stat-value overview-stat-value--${ranOk ? 'ok' : 'error'}`}>
                  {ranOk ? 'Success' : latestTrace.status}
                </span>
                <span className="overview-stat-label">Status</span>
              </div>
              <div className="overview-stat">
                <span className="overview-stat-value">{formatLatency(latestTrace.latency_ms)}</span>
                <span className="overview-stat-label">Latency</span>
              </div>
              <div className="overview-stat">
                <span className="overview-stat-value">{latestTrace.total_tokens.toLocaleString()}</span>
                <span className="overview-stat-label">Tokens</span>
              </div>
              <div className="overview-stat">
                <span className="overview-stat-value">${latestTrace.cost_usd.toFixed(4)}</span>
                <span className="overview-stat-label">Cost</span>
              </div>
            </div>
            <div className="overview-run-meta">
              <span>{latestTrace.effective_provider && latestTrace.effective_model
                ? `${latestTrace.effective_provider}/${latestTrace.effective_model}`
                : `${latestTrace.provider}/${latestTrace.model}`}</span>
              <span>{new Date(latestTrace.created_at).toLocaleString()}</span>
            </div>
            {(latestTrace.attempt_count ?? 1) > 1 || latestTrace.used_fallback ? (
              <div className="overview-run-note">
                Needed {latestTrace.attempt_count ?? 1} attempt{(latestTrace.attempt_count ?? 1) === 1 ? '' : 's'}
                {latestTrace.used_fallback ? ' and switched to the fallback model' : ''}.
              </div>
            ) : null}
            {recentReliability.total > 1 && (recentReliability.retryRuns > 0 || recentReliability.fallbackRuns > 0) && (
              <div className="overview-run-note">
                Last {recentReliability.total} runs: {recentReliability.retryRuns} retried, {recentReliability.fallbackRuns} used the fallback ({recentReliability.fallbackRate}%).
              </div>
            )}
          </>
        ) : (
          <div className="overview-muted">No runs yet. Open the Run tab to try it.</div>
        )}
      </section>

      <PublishGateCard appId={currentApp.id} />

      {/* Composition */}
      <section className="overview-card">
        <div className="overview-card-head">
          <h3 className="overview-title">Composition</h3>
          <span className="overview-muted">{pipelineKind}</span>
        </div>
        <div className="overview-node-chips">
          {nodeCountEntries.length === 0 ? (
            <span className="overview-muted">No nodes yet</span>
          ) : (
            nodeCountEntries.map(([kind, count]) => (
              <span key={kind} className="overview-chip">
                <NodeIcon kind={kind} size={12} />
                {NODE_LABELS[kind] ?? kind}{count > 1 ? ` ×${count}` : ''}
              </span>
            ))
          )}
        </div>
        <div className="overview-run-meta">
          <span>{nodes.length} nodes · {edges.length} connections</span>
        </div>
      </section>

      <footer className="overview-footer">
        <span title="App ID">{currentApp.id}</span>
        <span>Updated {appUpdated}</span>
      </footer>
    </div>
  )
}
