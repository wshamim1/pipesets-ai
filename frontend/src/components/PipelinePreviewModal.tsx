import { useEffect, useState } from 'react'
import type { Edge, Node } from '@xyflow/react'
import { API_BASE } from '../types'
import { ReadOnlyFlow } from './ReadOnlyFlow'
import { fetchAppVersions } from '../utils/publishedApps'
import {
  closePipelinePreview,
  openPipelinePreview,
  popPipelinePreview,
  usePipelinePreviewStack,
} from '../utils/pipelinePreview'

interface VersionDetail {
  version: number
  name: string
  description: string
  flow_data: { nodes?: Node[]; edges?: Edge[] }
  created_at: string
}

/** Read-only view of the published pipeline a pipeline child calls. Mounted once in App. */
export function PipelinePreviewModal() {
  const stack = usePipelinePreviewStack()
  const current = stack[stack.length - 1]
  const [detail, setDetail] = useState<VersionDetail | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!current) return
    let cancelled = false
    setDetail(null)
    setError('')
    const load = async () => {
      // version 0 = legacy "always latest" child — show the newest snapshot
      const version = current.version || (await fetchAppVersions(current.appId))[0]?.version
      if (!version) throw new Error('This pipeline has no published version yet.')
      const r = await fetch(`${API_BASE}/api/apps/${encodeURIComponent(current.appId)}/versions/${version}`)
      if (!r.ok) throw new Error(r.status === 404 ? `v${version} is not available.` : `HTTP ${r.status}`)
      return (await r.json()) as VersionDetail
    }
    load()
      .then((d) => { if (!cancelled) setDetail(d) })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)) })
    return () => { cancelled = true }
  }, [current])

  useEffect(() => {
    if (!current) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') closePipelinePreview() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [current])

  if (!current) return null

  return (
    <div className="modal-backdrop" onClick={closePipelinePreview}>
      <div className="modal-card pipeline-preview-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="pipeline-preview-title">
            <nav className="pipeline-preview-crumbs">
              {stack.map((s, i) => (
                <span key={`${s.appId}-${i}`}>
                  {i > 0 && <span className="pipeline-preview-sep">›</span>}
                  {i < stack.length - 1
                    ? <button type="button" onClick={() => popPipelinePreview(i)}>{s.name}</button>
                    : <strong>{s.name}</strong>}
                </span>
              ))}
            </nav>
            {detail && (
              <span className="field-hint">
                v{detail.version} · {(detail.flow_data.nodes ?? []).length} nodes · read-only
                {detail.description ? ` · ${detail.description}` : ''}
              </span>
            )}
          </div>
          <button type="button" className="modal-close-btn" onClick={closePipelinePreview}>✕</button>
        </div>
        <div className="pipeline-preview-body">
          {error && <div className="pipeline-preview-msg error">{error}</div>}
          {!error && !detail && <div className="pipeline-preview-msg">Loading…</div>}
          {detail && (
            <ReadOnlyFlow
              key={`${current.appId}-${detail.version}`}
              nodes={detail.flow_data.nodes ?? []}
              edges={detail.flow_data.edges ?? []}
              onNodeClick={(_, node) => {
                const d = node.data as Record<string, any>
                if (node.type === 'child_agent' && d.kind === 'pipeline' && d.app_id) {
                  openPipelinePreview({ appId: d.app_id, version: d.app_version ?? 0, name: d.app_name || d.label })
                }
              }}
            />
          )}
        </div>
      </div>
    </div>
  )
}
