import { useState, useEffect } from 'react'
import { API_BASE, type TraceRecord } from '../types'
import { useCredentials } from '../context/CredentialsContext'
import { spanKind } from '../utils/traceFlags'

/** What /api/agents/runs/{id} says about a checkpointed LLM run (for re-running it from a step). */
interface RunInfo {
  rerunnable?: boolean
  tool_results?: Record<string, string>
  forked_from?: { run_id: string; step: string; edited: boolean } | null
}

interface RerunResult {
  run_id?: string
  status?: string
  output?: string
  error?: string | null
  from: string
}

interface Props {
  trace: TraceRecord | null
  allRunTraces?: TraceRecord[]
  appName?: string
  onClose: () => void
}

export function TraceDetailDrawer({ trace, allRunTraces = [], appName, onClose }: Props) {
  const [activeTab, setActiveTab] = useState<'overview' | 'prompt' | 'output' | 'spans' | 'raw'>('overview')
  const [copiedKey, setCopiedKey] = useState<string | null>(null)
  const { resolveApiKey } = useCredentials()
  // Checkpointed LLM runs can be re-run from any saved step (time travel). State is kept per run
  // id, so opening another trace starts clean.
  const runId = trace?.run_id
  const [fetched, setFetched] = useState<{ runId: string; info: RunInfo | null } | null>(null)
  const [editingState, setEditing] = useState<{ runId?: string; key: string; text: string } | null>(null)
  const [rerunBusy, setRerunBusy] = useState<string | null>(null)
  const [rerunState, setRerun] = useState<(RerunResult & { runId?: string }) | null>(null)
  const runInfo = fetched && fetched.runId === runId ? fetched.info : null
  const editing = editingState?.runId === runId ? editingState : null
  const rerun = rerunState?.runId === runId ? rerunState : null

  useEffect(() => {
    if (!runId) return
    let live = true
    fetch(`${API_BASE}/api/agents/runs/${encodeURIComponent(runId)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (live) setFetched({ runId, info: d }) })
      .catch(() => {})
    return () => { live = false }
  }, [runId])

  const rerunFrom = async (step: string, editedOutput?: string) => {
    if (!runId) return
    setRerunBusy(step)
    setRerun(null)
    try {
      const res = await fetch(`${API_BASE}/api/agents/runs/${encodeURIComponent(runId)}/rerun`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          from_step: step, edited_output: editedOutput,
          // The browser's key store, as for editor runs; the server falls back to the project's vault
          provider_keys: Object.fromEntries(['openai', 'anthropic', 'groq', 'gemini', 'mistral']
            .map((p) => [p, resolveApiKey(p)]).filter(([, k]) => k)),
        }),
      })
      const d = await res.json().catch(() => ({}))
      setRerun(res.ok ? { ...d, from: step, runId } : { status: 'failed', error: typeof d.detail === 'string' ? d.detail : res.statusText, from: step, runId })
      if (res.ok) setEditing(null)
    } catch (e: any) {
      setRerun({ status: 'failed', error: e.message, from: step, runId })
    } finally {
      setRerunBusy(null)
    }
  }

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  if (!trace) return null

  const isSuccess = trace.status === 'success'
  const isError = trace.status === 'error'
  const isFallback = Boolean(trace.used_fallback && Number(trace.used_fallback) > 0)
  const isRetried = (trace.attempt_count ?? 1) > 1

  const copyToClipboard = (text: string, key: string) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopiedKey(key)
      setTimeout(() => setCopiedKey(null), 2000)
    })
  }

  // Parse metadata if present
  let parsedMeta: Record<string, any> = {}
  if (trace.metadata_json) {
    try {
      parsedMeta = JSON.parse(trace.metadata_json)
    } catch {
      parsedMeta = {}
    }
  }

  // Parse spans_json into a typed array
  interface SpanRecord {
    span_type: 'llm' | 'tool' | string
    step: number
    name: string
    latency_ms: number
    provider?: string
    model?: string
    prompt_tokens?: number
    completion_tokens?: number
    total_tokens?: number
    cost_usd?: number
    finish_reason?: string
    tool_calls_count?: number
    tool_id?: string
    input_preview?: string
    output_preview?: string
    status: 'success' | 'error' | string
    checkpoint_key?: string | null   // the saved step behind it: re-run the run from here
    resumed?: boolean                // replayed from the checkpoint by a resume
    collection?: string              // retrieval
    chunks?: number                  // retrieval: chunks returned
    error?: string
  }
  let parsedSpans: SpanRecord[] = []
  if (trace.spans_json) {
    try {
      parsedSpans = JSON.parse(trace.spans_json)
    } catch {
      parsedSpans = []
    }
  }
  // Embedding runs inside its retrieval span, so it isn't added twice
  const totalSpanMs = parsedSpans.reduce((acc, s) => acc + (s.span_type === 'embedding' ? 0 : s.latency_ms), 0)
    || trace.latency_ms || 1

  // Generate OpenTelemetry compliant span representation
  const otelSpan = {
    traceId: trace.run_id.replace(/-/g, '').padEnd(32, '0'),
    spanId: trace.id.replace(/-/g, '').slice(0, 16),
    name: `${trace.node_type || 'llm'}:${trace.model}`,
    kind: 'SPAN_KIND_INTERNAL',
    startTimeUnixNano: new Date(trace.created_at).getTime() * 1_000_000,
    endTimeUnixNano: (new Date(trace.created_at).getTime() + trace.latency_ms) * 1_000_000,
    attributes: {
      'gen_ai.system': trace.provider,
      'gen_ai.request.model': trace.model,
      'gen_ai.response.model': trace.effective_model || trace.model,
      'gen_ai.usage.prompt_tokens': trace.prompt_tokens,
      'gen_ai.usage.completion_tokens': trace.completion_tokens,
      'gen_ai.usage.total_tokens': trace.total_tokens,
      'gen_ai.cost.usd': trace.cost_usd,
      'app.pipeline_id': trace.app_id || 'default',
      'app.node_id': trace.node_id || '',
      'app.attempt_count': trace.attempt_count || 1,
      'app.used_fallback': isFallback,
      'status.code': isSuccess ? 'OK' : 'ERROR',
      ...(trace.error ? { 'status.message': trace.error } : {}),
    },
  }

  const exportOTel = () => {
    const jsonStr = JSON.stringify(otelSpan, null, 2)
    copyToClipboard(jsonStr, 'otel')
  }

  return (
    <div className="trace-drawer-backdrop" onClick={onClose}>
      <div className="trace-drawer" onClick={(e) => e.stopPropagation()}>
        {/* ── Drawer Header ── */}
        <div className="trace-drawer-header">
          <div className="trace-drawer-header-left">
            <div className="trace-drawer-badges">
              <span className={`trace-status-badge ${isSuccess ? 'success' : 'error'}`}>
                {isSuccess ? '● Success' : '✕ Error'}
              </span>
              {isFallback && <span className="trace-badge fallback">⇄ Fallback Used</span>}
              {isRetried && <span className="trace-badge retry">↻ Attempt {trace.attempt_count}</span>}
              <span className="trace-badge node-type">{trace.node_type.toUpperCase()}</span>
            </div>
            <h2 className="trace-drawer-title">
              Trace <span className="trace-id-mono">{trace.id.slice(0, 12)}…</span>
            </h2>
            <div className="trace-drawer-sub">
              <span>Run: <strong className="mono">{trace.run_id.slice(0, 12)}</strong></span>
              {appName && <span>• Pipeline: <strong>{appName}</strong></span>}
              <span>• {new Date(trace.created_at).toLocaleString()}</span>
            </div>
          </div>

          <div className="trace-drawer-header-actions">
            <button
              type="button"
              className="trace-action-btn"
              onClick={() => copyToClipboard(JSON.stringify(trace, null, 2), 'trace-json')}
              title="Copy complete trace JSON"
            >
              {copiedKey === 'trace-json' ? '✓ Copied JSON' : '📋 Copy JSON'}
            </button>
            <button
              type="button"
              className="trace-action-btn"
              onClick={exportOTel}
              title="Copy OpenTelemetry / LangSmith span JSON"
            >
              {copiedKey === 'otel' ? '✓ OTel Copied' : '🔭 Export OTel'}
            </button>
            <button type="button" className="trace-drawer-close-btn" onClick={onClose} title="Close drawer (Esc)">
              ✕
            </button>
          </div>
        </div>

        {/* ── Metric Cards Ribbon ── */}
        <div className="trace-metric-strip">
          <div className="trace-metric-card">
            <span className="trace-metric-label">Latency</span>
            <span className="trace-metric-val">{trace.latency_ms >= 1000 ? `${(trace.latency_ms / 1000).toFixed(2)}s` : `${trace.latency_ms}ms`}</span>
            <div className="trace-metric-sub">
              {trace.latency_ms > 3000 ? '🔴 High' : trace.latency_ms > 1000 ? '🟡 Moderate' : '🟢 Fast'}
            </div>
          </div>
          <div className="trace-metric-card">
            <span className="trace-metric-label">Tokens</span>
            <span className="trace-metric-val">{trace.total_tokens.toLocaleString()}</span>
            <div className="trace-metric-sub">
              ↑{trace.prompt_tokens.toLocaleString()} prompt · ↓{trace.completion_tokens.toLocaleString()} comp
            </div>
          </div>
          <div className="trace-metric-card">
            <span className="trace-metric-label">Estimated Cost</span>
            <span className="trace-metric-val">${trace.cost_usd.toFixed(5)}</span>
            <div className="trace-metric-sub">
              {trace.total_tokens > 0 ? `$${((trace.cost_usd / trace.total_tokens) * 1000).toFixed(4)}/1k tok` : '—'}
            </div>
          </div>
          <div className="trace-metric-card">
            <span className="trace-metric-label">Model</span>
            <span className="trace-metric-val mono" title={`${trace.provider}/${trace.model}`}>
              {trace.model}
            </span>
            <div className="trace-metric-sub">{trace.provider}</div>
          </div>
        </div>

        {/* ── Tabs Navigation ── */}
        <div className="trace-drawer-tabs">
          <button
            type="button"
            className={`trace-tab-btn ${activeTab === 'overview' ? 'active' : ''}`}
            onClick={() => setActiveTab('overview')}
          >
            📊 Diagnostics & Spans
          </button>
          <button
            type="button"
            className={`trace-tab-btn ${activeTab === 'prompt' ? 'active' : ''}`}
            onClick={() => setActiveTab('prompt')}
          >
            📥 Input / Prompt
          </button>
          <button
            type="button"
            className={`trace-tab-btn ${activeTab === 'output' ? 'active' : ''}`}
            onClick={() => setActiveTab('output')}
          >
            📤 Output / Response
          </button>
          {isError && (
            <button
              type="button"
              className={`trace-tab-btn error ${activeTab === 'overview' ? '' : ''}`}
              onClick={() => setActiveTab('overview')}
            >
              🚨 Error Stack
            </button>
          )}
          <button
            type="button"
            className={`trace-tab-btn ${activeTab === 'spans' ? 'active' : ''}`}
            onClick={() => setActiveTab('spans')}
          >
            🔥 Flame Graph
          </button>
          <button
            type="button"
            className={`trace-tab-btn ${activeTab === 'raw' ? 'active' : ''}`}
            onClick={() => setActiveTab('raw')}
          >
            {'{}'} Raw JSON
          </button>
        </div>

        {/* ── Tab Content ── */}
        <div className="trace-drawer-body">
          {/* TAB 1: OVERVIEW */}
          {activeTab === 'overview' && (
            <div className="trace-section-stack">
              {/* Fallback diagnostic alert if applicable */}
              {isFallback && (
                <div className="trace-diagnostic-banner warning">
                  <div className="banner-title">⇄ Automatic Fallback Activated</div>
                  <div className="banner-desc">
                    Initial provider/model <code>{trace.provider}/{trace.model}</code> failed or timed out.
                    Execution was automatically routed to <strong>{trace.effective_provider || trace.provider}/{trace.effective_model || trace.model}</strong> on attempt {trace.attempt_count || 2}.
                  </div>
                </div>
              )}

              {/* Error diagnostic alert if applicable */}
              {isError && (
                <div className="trace-diagnostic-banner danger">
                  <div className="banner-title">✕ Execution Failed</div>
                  <div className="banner-desc">
                    <strong>Error:</strong> {trace.error || 'Unknown runtime error'}
                  </div>
                </div>
              )}

              {/* Attributes Table */}
              <div className="trace-card">
                <div className="trace-card-title">Execution Attributes</div>
                <table className="trace-attrib-table">
                  <tbody>
                    <tr>
                      <td className="attrib-key">Trace ID</td>
                      <td className="attrib-val mono">
                        {trace.id}
                        <button
                          type="button"
                          className="copy-mini-btn"
                          onClick={() => copyToClipboard(trace.id, 'tid')}
                        >
                          {copiedKey === 'tid' ? '✓' : 'Copy'}
                        </button>
                      </td>
                    </tr>
                    <tr>
                      <td className="attrib-key">Run ID</td>
                      <td className="attrib-val mono">
                        {trace.run_id}
                        <button
                          type="button"
                          className="copy-mini-btn"
                          onClick={() => copyToClipboard(trace.run_id, 'rid')}
                        >
                          {copiedKey === 'rid' ? '✓' : 'Copy'}
                        </button>
                      </td>
                    </tr>
                    <tr>
                      <td className="attrib-key">Pipeline / App ID</td>
                      <td className="attrib-val">{appName || trace.app_id || '—'}</td>
                    </tr>
                    <tr>
                      <td className="attrib-key">Node</td>
                      <td className="attrib-val">
                        <span className="badge-node">{trace.node_type}</span> {trace.node_id ? `(${trace.node_id})` : ''}
                      </td>
                    </tr>
                    <tr>
                      <td className="attrib-key">Configured Provider & Model</td>
                      <td className="attrib-val mono">{trace.provider} / {trace.model}</td>
                    </tr>
                    {trace.effective_model && trace.effective_model !== trace.model && (
                      <tr>
                        <td className="attrib-key">Effective Model (Fallback)</td>
                        <td className="attrib-val mono text-amber">
                          {trace.effective_provider || trace.provider} / {trace.effective_model}
                        </td>
                      </tr>
                    )}
                    <tr>
                      <td className="attrib-key">Execution Status</td>
                      <td className="attrib-val">
                        <span className={`status-pill ${trace.status}`}>{trace.status.toUpperCase()}</span>
                      </td>
                    </tr>
                    <tr>
                      <td className="attrib-key">Attempts Count</td>
                      <td className="attrib-val">{trace.attempt_count ?? 1}</td>
                    </tr>
                    <tr>
                      <td className="attrib-key">Timestamp (UTC)</td>
                      <td className="attrib-val">{trace.created_at}</td>
                    </tr>
                    {parsedMeta.finish_reason && (
                      <tr>
                        <td className="attrib-key">Finish Reason</td>
                        <td className="attrib-val mono">{parsedMeta.finish_reason}</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              {/* Token Breakdown Visualizer */}
              <div className="trace-card">
                <div className="trace-card-title">Token & Cost Breakdown</div>
                <div className="trace-token-bar-container">
                  <div className="trace-token-bar-wrapper">
                    <div
                      className="trace-token-bar prompt"
                      style={{
                        width: `${trace.total_tokens > 0 ? (trace.prompt_tokens / trace.total_tokens) * 100 : 50}%`,
                      }}
                      title={`Prompt Tokens: ${trace.prompt_tokens}`}
                    />
                    <div
                      className="trace-token-bar completion"
                      style={{
                        width: `${trace.total_tokens > 0 ? (trace.completion_tokens / trace.total_tokens) * 100 : 50}%`,
                      }}
                      title={`Completion Tokens: ${trace.completion_tokens}`}
                    />
                  </div>
                  <div className="trace-token-legend">
                    <div className="legend-item">
                      <span className="legend-dot prompt" />
                      <span>Prompt: <strong>{trace.prompt_tokens.toLocaleString()}</strong> ({trace.total_tokens > 0 ? Math.round((trace.prompt_tokens / trace.total_tokens) * 100) : 0}%)</span>
                    </div>
                    <div className="legend-item">
                      <span className="legend-dot completion" />
                      <span>Completion: <strong>{trace.completion_tokens.toLocaleString()}</strong> ({trace.total_tokens > 0 ? Math.round((trace.completion_tokens / trace.total_tokens) * 100) : 0}%)</span>
                    </div>
                    <div className="legend-item total">
                      <span>Total: <strong>{trace.total_tokens.toLocaleString()} tokens</strong> (${trace.cost_usd.toFixed(5)})</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Multi-span waterfall for same run if available */}
              {allRunTraces.length > 1 && (
                <div className="trace-card">
                  <div className="trace-card-title">Run Waterfall Spans ({allRunTraces.length})</div>
                  <div className="trace-waterfall-list">
                    {allRunTraces.map((sp, idx) => {
                      const maxMs = Math.max(...allRunTraces.map((s) => s.latency_ms), 1)
                      const pct = Math.max(4, Math.round((sp.latency_ms / maxMs) * 100))
                      const isCurrent = sp.id === trace.id
                      return (
                        <div key={sp.id} className={`waterfall-span-row ${isCurrent ? 'current' : ''}`}>
                          <div className="span-meta">
                            <span className="span-idx">#{idx + 1}</span>
                            <span className="span-node-type">{sp.node_type}</span>
                            <span className="span-model mono">{sp.provider}/{sp.model}</span>
                            <span className="span-time">{sp.latency_ms}ms</span>
                          </div>
                          <div className="span-bar-track">
                            <div
                              className={`span-bar-fill ${sp.status === 'error' ? 'error' : sp.latency_ms > 2000 ? 'slow' : 'normal'}`}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* TAB 2: PROMPT */}
          {activeTab === 'prompt' && (
            <div className="trace-section-stack">
              <div className="trace-card">
                <div className="trace-card-header-row">
                  <div className="trace-card-title">Prompt / Input Payload</div>
                  {trace.prompt_preview && (
                    <button
                      type="button"
                      className="copy-mini-btn"
                      onClick={() => copyToClipboard(trace.prompt_preview || '', 'prompt')}
                    >
                      {copiedKey === 'prompt' ? '✓ Copied' : '📋 Copy Prompt'}
                    </button>
                  )}
                </div>
                {trace.prompt_preview ? (
                  <pre className="trace-code-block">{trace.prompt_preview}</pre>
                ) : (
                  <div className="trace-empty-box">
                    Prompt preview was not stored for this trace row (available for newer executions).
                  </div>
                )}
              </div>
            </div>
          )}

          {/* TAB 3: OUTPUT */}
          {activeTab === 'output' && (
            <div className="trace-section-stack">
              <div className="trace-card">
                <div className="trace-card-header-row">
                  <div className="trace-card-title">Model Response / Output</div>
                  {trace.output_preview && (
                    <button
                      type="button"
                      className="copy-mini-btn"
                      onClick={() => copyToClipboard(trace.output_preview || '', 'output')}
                    >
                      {copiedKey === 'output' ? '✓ Copied' : '📋 Copy Output'}
                    </button>
                  )}
                </div>
                {trace.output_preview ? (
                  <pre className="trace-code-block output">{trace.output_preview}</pre>
                ) : isError ? (
                  <div className="trace-empty-box error">
                    No output generated due to failure: {trace.error}
                  </div>
                ) : (
                  <div className="trace-empty-box">
                    Output preview not recorded for this legacy record.
                  </div>
                )}
              </div>

              {parsedMeta.tools_used && Array.isArray(parsedMeta.tools_used) && parsedMeta.tools_used.length > 0 && (
                <div className="trace-card">
                  <div className="trace-card-title">Tools Executed ({parsedMeta.tools_used.length})</div>
                  <div className="trace-tools-list">
                    {parsedMeta.tools_used.map((tool: any, idx: number) => (
                      <div key={idx} className="trace-tool-item">
                        <span className="tool-icon">⚡</span>
                        <span className="tool-name">{typeof tool === 'string' ? tool : tool.name || JSON.stringify(tool)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* TAB 4: FLAME GRAPH */}
          {activeTab === 'spans' && (
            <div className="trace-section-stack">
              {parsedSpans.length === 0 ? (
                <div className="trace-card">
                  <div className="trace-card-title">Execution Spans</div>
                  <div className="trace-empty-box">
                    No span data available for this trace. Spans are recorded for multi-step ReAct agent runs with real LLM providers. Re-run the pipeline to generate span data.
                  </div>
                </div>
              ) : (
                <>
                  {/* Summary ribbon */}
                  <div className="flame-summary-row">
                    <div className="flame-summary-chip">
                      <span className="flame-summary-label">Total Spans</span>
                      <span className="flame-summary-val">{parsedSpans.length}</span>
                    </div>
                    <div className="flame-summary-chip">
                      <span className="flame-summary-label">LLM Steps</span>
                      <span className="flame-summary-val">{parsedSpans.filter(s => s.span_type === 'llm').length}</span>
                    </div>
                    <div className="flame-summary-chip">
                      <span className="flame-summary-label">Tool Calls</span>
                      <span className="flame-summary-val">{parsedSpans.filter(s => s.span_type === 'tool').length}</span>
                    </div>
                    <div className="flame-summary-chip">
                      <span className="flame-summary-label">Total Span Time</span>
                      <span className="flame-summary-val">{totalSpanMs >= 1000 ? `${(totalSpanMs / 1000).toFixed(2)}s` : `${totalSpanMs}ms`}</span>
                    </div>
                  </div>

                  {/* Flame graph / waterfall */}
                  <div className="trace-card">
                    <div className="trace-card-title">Execution Timeline</div>
                    <div className="flame-axis-row">
                      <span className="flame-axis-label">0ms</span>
                      <span className="flame-axis-label">{Math.round(totalSpanMs / 2)}ms</span>
                      <span className="flame-axis-label">{totalSpanMs}ms</span>
                    </div>
                    <div className="flame-chart">
                      {parsedSpans.map((span, idx) => {
                        const widthPct = Math.max(2, Math.round((span.latency_ms / totalSpanMs) * 100))
                        const kind = spanKind(span.span_type)
                        const isSlow = span.latency_ms > 2000
                        const isError = span.status === 'error'
                        const colorClass = isError ? 'flame-bar--error' : isSlow ? 'flame-bar--slow' : `flame-bar--${kind.css}`
                        return (
                          <div key={idx} className="flame-row">
                            <div className="flame-row-label">
                              <span className={`flame-type-chip ${kind.css}`}>
                                {kind.icon} {span.span_type.toUpperCase()}
                              </span>
                              <span className="flame-row-name" title={span.name}>{span.name}</span>
                            </div>
                            <div className="flame-track">
                              <div
                                className={`flame-bar ${colorClass}`}
                                style={{ width: `${widthPct}%` }}
                                title={`${span.name}: ${span.latency_ms}ms`}
                              >
                                <span className="flame-bar-label">
                                  {span.latency_ms >= 1000 ? `${(span.latency_ms / 1000).toFixed(2)}s` : `${span.latency_ms}ms`}
                                </span>
                              </div>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>

                  {/* Time travel: result of a re-run from a step */}
                  {(runInfo?.forked_from || rerun) && (
                    <div className="trace-card rerun-card">
                      {runInfo?.forked_from && (
                        <div className="rerun-note">
                          ↻ Re-run of <code>{runInfo.forked_from.run_id.slice(0, 8)}</code> from step{' '}
                          <code>{runInfo.forked_from.step}</code>{runInfo.forked_from.edited ? ' with an edited tool result' : ''}.
                        </div>
                      )}
                      {rerun && (
                        <div className={`rerun-result ${rerun.status === 'completed' ? 'ok' : 'failed'}`}>
                          <div className="trace-card-title">
                            Re-run from <code>{rerun.from}</code> · {rerun.status}
                            {rerun.run_id && <span className="rerun-id"> · new run <code>{rerun.run_id.slice(0, 8)}</code> (in Traces)</span>}
                          </div>
                          {rerun.output && <pre className="rerun-output">{rerun.output}</pre>}
                          {rerun.error && <div className="rerun-error">{rerun.error}</div>}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Per-span detail cards */}
                  <div className="trace-card">
                    <div className="trace-card-title">Span Details</div>
                    {runInfo?.rerunnable && (
                      <div className="rerun-hint">
                        Each step is saved, so the run can be re-run from any of them as a new run: steps before it are
                        reused, that step and the rest run again against the app's current flow. A tool's result can be edited first.
                      </div>
                    )}
                    <div className="flame-detail-list">
                      {parsedSpans.map((span, idx) => {
                        const kind = spanKind(span.span_type)
                        const isLlm = kind.css === 'llm'
                        return (
                          <div key={idx} className={`flame-detail-card ${span.status === 'error' ? 'error' : ''}`}>
                            <div className="flame-detail-header">
                              <span className={`flame-type-chip ${kind.css}`}>
                                {kind.icon} {kind.label}
                              </span>
                              <span className="flame-detail-name">{span.name}</span>
                              {span.resumed && <span className="flame-resumed-chip" title="Reused from the checkpoint by a resume">resumed</span>}
                              <span className="flame-detail-latency">
                                {span.latency_ms >= 1000 ? `${(span.latency_ms / 1000).toFixed(2)}s` : `${span.latency_ms}ms`}
                              </span>
                              <span className={`flame-status-dot ${span.status}`} title={span.status} />
                            </div>
                            <div className="flame-detail-body">
                              {isLlm ? (
                                <div className="flame-kv-grid">
                                  {span.provider && <><span className="flame-kv-key">Provider</span><span className="flame-kv-val mono">{span.provider}</span></>}
                                  {span.model && <><span className="flame-kv-key">Model</span><span className="flame-kv-val mono">{span.model}</span></>}
                                  {span.finish_reason && <><span className="flame-kv-key">Finish Reason</span><span className="flame-kv-val mono">{span.finish_reason}</span></>}
                                  {(span.total_tokens ?? 0) > 0 && <>
                                    <span className="flame-kv-key">Tokens</span>
                                    <span className="flame-kv-val">
                                      <span className="tok-prompt">{span.prompt_tokens ?? 0}↑</span>
                                      {' + '}
                                      <span className="tok-comp">{span.completion_tokens ?? 0}↓</span>
                                      {' = '}
                                      <strong>{span.total_tokens ?? 0}</strong>
                                    </span>
                                  </>}
                                  {(span.cost_usd ?? 0) > 0 && <><span className="flame-kv-key">Cost</span><span className="flame-kv-val">${span.cost_usd?.toFixed(5)}</span></>}
                                  {(span.tool_calls_count ?? 0) > 0 && <><span className="flame-kv-key">Tool Calls Triggered</span><span className="flame-kv-val">{span.tool_calls_count}</span></>}
                                </div>
                              ) : kind.css === 'phase' ? (
                                <div className="flame-kv-grid">
                                  {span.collection && <><span className="flame-kv-key">Collection</span><span className="flame-kv-val mono">{span.collection}</span></>}
                                  {span.chunks !== undefined && <><span className="flame-kv-key">Chunks</span><span className="flame-kv-val">{span.chunks}</span></>}
                                  {span.provider && <><span className="flame-kv-key">Provider</span><span className="flame-kv-val mono">{span.provider}</span></>}
                                  {span.model && <><span className="flame-kv-key">Model</span><span className="flame-kv-val mono">{span.model}</span></>}
                                  {span.error && <><span className="flame-kv-key">Blocked</span><span className="flame-kv-val">{span.error}</span></>}
                                </div>
                              ) : (
                                <div className="flame-kv-grid">
                                  {span.tool_id && <><span className="flame-kv-key">Tool ID</span><span className="flame-kv-val mono">{span.tool_id}</span></>}
                                  {span.input_preview && (
                                    <>
                                      <span className="flame-kv-key">Input</span>
                                      <span className="flame-kv-val mono flame-preview">{span.input_preview}</span>
                                    </>
                                  )}
                                  {span.output_preview && (
                                    <>
                                      <span className="flame-kv-key">Output</span>
                                      <span className="flame-kv-val mono flame-preview">{span.output_preview}</span>
                                    </>
                                  )}
                                </div>
                              )}
                              {runInfo?.rerunnable && span.checkpoint_key && (() => {
                                const key = span.checkpoint_key
                                const isEditing = editing?.key === key
                                return (
                                  <div className="rerun-actions">
                                    {isEditing && (
                                      <textarea className="rerun-edit" rows={6} value={editing.text}
                                        aria-label="Tool result to continue with"
                                        onChange={(e) => setEditing({ runId, key, text: e.target.value })} />
                                    )}
                                    <div className="rerun-buttons">
                                      {isEditing ? (
                                        <>
                                          <button type="button" className="copy-mini-btn" disabled={rerunBusy !== null}
                                            onClick={() => rerunFrom(key, editing.text)}>
                                            {rerunBusy === key ? 'Running…' : '↻ Continue with this result'}
                                          </button>
                                          <button type="button" className="copy-mini-btn" onClick={() => setEditing(null)}>Cancel</button>
                                        </>
                                      ) : (
                                        <>
                                          <button type="button" className="copy-mini-btn" disabled={rerunBusy !== null}
                                            title={isLlm ? 'Call the model again from this step' : 'Run this tool again, then continue'}
                                            onClick={() => rerunFrom(key)}>
                                            {rerunBusy === key ? 'Running…' : '↻ Re-run from here'}
                                          </button>
                                          {!isLlm && (
                                            <button type="button" className="copy-mini-btn" disabled={rerunBusy !== null}
                                              onClick={() => setEditing({ runId, key, text: runInfo.tool_results?.[key] ?? span.output_preview ?? '' })}>
                                              ✎ Edit result
                                            </button>
                                          )}
                                        </>
                                      )}
                                    </div>
                                  </div>
                                )
                              })()}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                </>
              )}
            </div>
          )}

          {/* TAB 5: RAW JSON */}
          {activeTab === 'raw' && (
            <div className="trace-section-stack">
              <div className="trace-card">
                <div className="trace-card-header-row">
                  <div className="trace-card-title">Raw Trace Record JSON</div>
                  <button
                    type="button"
                    className="copy-mini-btn"
                    onClick={() => copyToClipboard(JSON.stringify(trace, null, 2), 'raw-json')}
                  >
                    {copiedKey === 'raw-json' ? '✓ Copied JSON' : '📋 Copy JSON'}
                  </button>
                </div>
                <pre className="trace-code-block json">{JSON.stringify(trace, null, 2)}</pre>
              </div>

              <div className="trace-card">
                <div className="trace-card-header-row">
                  <div className="trace-card-title">OpenTelemetry Span JSON</div>
                  <button
                    type="button"
                    className="copy-mini-btn"
                    onClick={() => copyToClipboard(JSON.stringify(otelSpan, null, 2), 'raw-otel')}
                  >
                    {copiedKey === 'raw-otel' ? '✓ Copied OTel' : '📋 Copy OTel JSON'}
                  </button>
                </div>
                <pre className="trace-code-block json">{JSON.stringify(otelSpan, null, 2)}</pre>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
