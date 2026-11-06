import { useCallback, useEffect, useState } from 'react'
import type { Edge, Node } from '@xyflow/react'
import { API_BASE } from '../../types'
import { ReadOnlyFlow } from '../ReadOnlyFlow'
import { renderMarkdownBlock } from '../../utils/renderMarkdown'
import { CATEGORY_LABELS, REQUIREMENT_ICONS, errorDetail, type ListingDetail } from './types'

const TRY_PROVIDERS = ['openai', 'anthropic', 'groq', 'gemini', 'mistral']

interface Props {
  listingId: string
  resolveApiKey: (provider: string) => string
  onClose: () => void
  onChanged: () => void
  onImported: (appId: string) => void
}

export function ListingDetailDrawer({ listingId, resolveApiKey, onClose, onChanged, onImported }: Props) {
  const [detail, setDetail] = useState<ListingDetail | null>(null)
  const [version, setVersion] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [prompt, setPrompt] = useState('')
  const [trying, setTrying] = useState(false)
  const [tryResult, setTryResult] = useState<{ ok: boolean; output: string; latency_ms: number } | null>(null)
  const [importing, setImporting] = useState(false)
  const [showCode, setShowCode] = useState(false)
  const [flowExpanded, setFlowExpanded] = useState(false)
  const [docsExpanded, setDocsExpanded] = useState(false)

  useEffect(() => {
    if (!flowExpanded) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setFlowExpanded(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [flowExpanded])

  const load = useCallback(async () => {
    setError('')
    const qs = version ? `?version=${version}` : ''
    const res = await fetch(`${API_BASE}/api/marketplace/listings/${listingId}${qs}`)
    if (!res.ok) {
      setError(await errorDetail(res, 'Failed to load listing'))
      return
    }
    setDetail(await res.json())
  }, [listingId, version])

  useEffect(() => {
    load()
  }, [load])

  const runTry = async () => {
    if (!detail || !prompt.trim()) return
    setTrying(true)
    setTryResult(null)
    setError('')
    try {
      const provider_keys = Object.fromEntries(TRY_PROVIDERS.map((p) => [p, resolveApiKey(p)]).filter(([, k]) => k))
      const res = await fetch(`${API_BASE}/api/marketplace/listings/${listingId}/try`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, version: detail.version, provider_keys }),
      })
      if (!res.ok) throw new Error(await errorDetail(res, 'Trial run failed'))
      setTryResult(await res.json())
      load() // refresh the trial counter
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Trial run failed')
    } finally {
      setTrying(false)
    }
  }

  const runImport = async () => {
    if (!detail) return
    if (detail.bundled_tools.length > 0 && !window.confirm(
      `This pipeline includes ${detail.bundled_tools.length} custom tool(s) whose code will run in your project. ` +
      'Review the code below before importing. Continue?')) return
    setImporting(true)
    setError('')
    try {
      const res = await fetch(`${API_BASE}/api/marketplace/listings/${listingId}/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ version: detail.version }),
      })
      if (!res.ok) throw new Error(await errorDetail(res, 'Import failed'))
      const data = await res.json()
      onImported(data.app_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Import failed')
    } finally {
      setImporting(false)
    }
  }

  const manage = async (method: 'PUT' | 'DELETE', body?: unknown) => {
    if (method === 'DELETE' && !window.confirm('Remove this listing? Copies others already imported are not affected.')) return
    const res = await fetch(`${API_BASE}/api/marketplace/listings/${listingId}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    })
    if (!res.ok) {
      setError(await errorDetail(res, 'Update failed'))
      return
    }
    onChanged()
    if (method === 'DELETE') onClose()
    else load()
  }

  return (
    <div className="mkt-overlay" onClick={onClose}>
      {flowExpanded && detail && (
        <div className="modal-backdrop" onClick={(e) => { e.stopPropagation(); setFlowExpanded(false) }}>
          <div className="modal-card pipeline-preview-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div className="pipeline-preview-title">
                <div className="pipeline-preview-crumbs"><strong>{detail.name}</strong></div>
                <span className="field-hint">
                  v{detail.version} · {(detail.flow_data?.nodes ?? []).length} nodes · read-only
                </span>
              </div>
              <button type="button" className="modal-close-btn" onClick={() => setFlowExpanded(false)}>✕</button>
            </div>
            <div className="pipeline-preview-body">
              <ReadOnlyFlow
                nodes={(detail.flow_data?.nodes ?? []) as Node[]}
                edges={(detail.flow_data?.edges ?? []) as Edge[]}
              />
            </div>
          </div>
        </div>
      )}
      <aside className="mkt-drawer" onClick={(e) => e.stopPropagation()} aria-label="Listing details">
        <div className="mkt-modal-head">
          <h2>{detail?.name ?? 'Loading…'}</h2>
          <button type="button" className="mkt-close" onClick={onClose} aria-label="Close">✕</button>
        </div>
        {error && <div className="mkt-note mkt-note--error" role="alert">{error}</div>}

        {detail && (
          <div className="mkt-stack">
            <div className="mkt-card-top">
              <span className="mkt-chip">{CATEGORY_LABELS[detail.category] ?? detail.category}</span>
              {detail.tags.map((t) => <span key={t} className="mkt-chip mkt-chip--muted">#{t}</span>)}
              {detail.visibility === 'tenant' && <span className="mkt-chip mkt-chip--private">Tenant only</span>}
            </div>
            <p className="mkt-muted">
              by {detail.publisher.user_name} · {detail.publisher.tenant_name} · ⬇ {detail.import_count} imports · ▶ {detail.try_count} trials
            </p>
            {detail.summary && <p className="mkt-lead">{detail.summary}</p>}
            {detail.description && detail.description !== detail.summary && <p className="mkt-desc">{detail.description}</p>}

            <div className="mkt-row">
              <label className="mkt-field"><span>Version</span>
                <select value={detail.version} onChange={(e) => setVersion(Number(e.target.value))}>
                  {detail.versions.map((v) => (
                    <option key={v.version} value={v.version}>v{v.version}{v.version === detail.latest_version ? ' (latest)' : ''}</option>
                  ))}
                </select>
              </label>
              <div className="mkt-field"><span>Nodes</span>
                <div className="mkt-node-types">
                  {Object.entries(detail.node_types).map(([t, n]) => <span key={t} className="mkt-chip mkt-chip--muted">{t.replace(/_/g, ' ')} ×{n}</span>)}
                </div>
              </div>
            </div>
            {detail.versions.find((v) => v.version === detail.version)?.changelog && (
              <p className="mkt-muted">What’s new: {detail.versions.find((v) => v.version === detail.version)?.changelog}</p>
            )}

            {detail.docs?.trim() && (
              <div className="mkt-section">
                <div className="mkt-label">
                  Docs
                  <button type="button" className="ops-link-btn" onClick={() => setDocsExpanded((v) => !v)}>
                    {docsExpanded ? 'Show less' : 'Read all'}
                  </button>
                </div>
                <div className={`mkt-docs${docsExpanded ? ' mkt-docs--open' : ''}`}>{renderMarkdownBlock(detail.docs)}</div>
              </div>
            )}

            <div className="mkt-section">
              <div className="mkt-label">
                Pipeline
                <button type="button" className="ops-link-btn" onClick={() => setFlowExpanded(true)}>⤢ Expand</button>
              </div>
              <div className="mkt-flow-preview">
                <ReadOnlyFlow
                  key={detail.version}
                  nodes={(detail.flow_data?.nodes ?? []) as Node[]}
                  edges={(detail.flow_data?.edges ?? []) as Edge[]}
                />
              </div>
            </div>

            <div className="mkt-section">
              <div className="mkt-label">What you’ll need</div>
              {detail.requirements.length === 0 ? (
                <p className="mkt-muted">Nothing — it runs as is.</p>
              ) : (
                <ul className="mkt-reqs">
                  {detail.requirements.map((r, i) => (
                    <li key={i}><span>{REQUIREMENT_ICONS[r.kind]}</span><div><strong>{r.label}</strong><small>{r.detail}</small></div></li>
                  ))}
                </ul>
              )}
            </div>

            {detail.bundled_tools.length > 0 && (
              <div className="mkt-section">
                <div className="mkt-label">
                  Custom tool code ({detail.bundled_tools.length})
                  <button type="button" className="ops-link-btn" onClick={() => setShowCode((s) => !s)}>{showCode ? 'Hide' : 'Review code'}</button>
                </div>
                <p className="mkt-note mkt-note--warn">Importing copies this code into your project, where it runs when the pipeline calls the tool.</p>
                {showCode && detail.bundled_tools.map((t) => (
                  <div key={t.ref} className="mkt-code-block">
                    <div><strong>{t.icon} {t.name}</strong> <small>{t.description}</small></div>
                    <pre>{t.code}</pre>
                  </div>
                ))}
              </div>
            )}

            <div className="mkt-section">
              <div className="mkt-label">Try it</div>
              {detail.can_try ? (
                <>
                  <textarea rows={3} className="mkt-try-input" value={prompt} onChange={(e) => setPrompt(e.target.value)}
                    placeholder="Send a test prompt — runs with your own API keys, nothing is saved" />
                  <div className="mkt-actions">
                    <button type="button" className="mkt-btn" onClick={runTry} disabled={trying || !prompt.trim()}>
                      {trying ? 'Running…' : '▶ Run trial'}
                    </button>
                  </div>
                  {tryResult && (
                    <div className={`mkt-try-output${tryResult.ok ? '' : ' mkt-try-output--error'}`}>
                      <small>{tryResult.ok ? 'Output' : 'Error'} · {tryResult.latency_ms} ms</small>
                      <pre>{tryResult.output}</pre>
                    </div>
                  )}
                </>
              ) : (
                <p className="mkt-muted">Not available before import. {detail.try_blocked_reason}</p>
              )}
            </div>

            <div className="mkt-actions mkt-actions--sticky">
              {detail.is_mine && (
                <>
                  <button type="button" className="mkt-btn" onClick={() => manage('PUT', { status: detail.status === 'listed' ? 'unlisted' : 'listed' })}>
                    {detail.status === 'listed' ? 'Unlist' : 'List again'}
                  </button>
                  <button type="button" className="mkt-btn" onClick={() => manage('PUT', { visibility: detail.visibility === 'public' ? 'tenant' : 'public' })}>
                    Make {detail.visibility === 'public' ? 'tenant-only' : 'public'}
                  </button>
                  <button type="button" className="mkt-btn mkt-btn--danger" onClick={() => manage('DELETE')}>Remove</button>
                </>
              )}
              <button type="button" className="mkt-btn mkt-btn--primary" onClick={runImport} disabled={importing}>
                {importing ? 'Importing…' : `⬇ Import v${detail.version} to my project`}
              </button>
            </div>
          </div>
        )}
      </aside>
    </div>
  )
}
