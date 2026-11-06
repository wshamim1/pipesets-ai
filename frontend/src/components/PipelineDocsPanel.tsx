import { useEffect, useState } from 'react'
import { API_BASE } from '../types'
import type { AppRecord, FlowEdge, FlowNode } from '../types'
import { useCredentials } from '../context/CredentialsContext'
import { renderMarkdownBlock } from '../utils/renderMarkdown'

interface Props {
  currentApp: AppRecord | null
  nodes: FlowNode[]
  edges: FlowEdge[]
  onAppUpdated: (app: AppRecord) => void
}

/** The pipeline's README: view, edit, or draft it with AI from the live canvas. */
export function PipelineDocsPanel({ currentApp, nodes, edges, onAppUpdated }: Props) {
  const { resolveApiKey } = useCredentials()
  const saved = currentApp?.docs ?? ''
  const [draft, setDraft] = useState<string | null>(null)   // null = viewing, string = editing
  const [generating, setGenerating] = useState(false)
  const [saving, setSaving] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Leave edit mode when switching to another app
  useEffect(() => {
    setDraft(null)
    setNote(null)
    setError(null)
  }, [currentApp?.id])

  if (!currentApp) {
    return <div className="docs-panel docs-panel--empty"><p>Save the pipeline to start its docs.</p></div>
  }

  const editing = draft !== null
  const dirty = editing && draft !== saved

  const generate = async () => {
    if (editing && dirty && !window.confirm('Replace your unsaved edits with a new AI draft?')) return
    if (!editing && saved.trim() && !window.confirm('Draft new docs? You can review them before saving.')) return
    setGenerating(true)
    setError(null)
    setNote(null)
    let examplePrompts: string[] = []
    try {
      examplePrompts = JSON.parse(localStorage.getItem(`pipesets:suggested-prompts:${currentApp.id}`) ?? '[]')
    } catch { /* storage unavailable */ }
    try {
      const r = await fetch(`${API_BASE}/api/apps/docs/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          flow_data: { nodes, edges },
          app_id: currentApp.id,
          name: currentApp.name,
          description: currentApp.description,
          example_prompts: examplePrompts,
          provider_keys: {
            openai: resolveApiKey('openai'), anthropic: resolveApiKey('anthropic'),
            groq: resolveApiKey('groq'), gemini: resolveApiKey('gemini'), mistral: resolveApiKey('mistral'),
          },
        }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { setError(typeof d.detail === 'string' ? d.detail : r.statusText); return }
      setDraft(d.docs ?? '')
      setNote(d.generated_by === 'template'
        ? d.note
        : `Drafted by ${d.generated_by} — review before saving.`)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setGenerating(false)
    }
  }

  const save = async () => {
    if (draft === null) return
    setSaving(true)
    setError(null)
    try {
      const r = await fetch(`${API_BASE}/api/apps/${currentApp.id}/docs`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ docs: draft }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { setError(typeof d.detail === 'string' ? d.detail : r.statusText); return }
      onAppUpdated(d)
      setDraft(null)
      setNote(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  const cancel = () => {
    if (dirty && !window.confirm('Discard your unsaved edits?')) return
    setDraft(null)
    setNote(null)
  }

  const generateLabel = generating ? 'Generating…' : saved.trim() || editing ? '↻ Regenerate' : '✨ Generate draft'

  return (
    <div className="docs-panel">
      <div className="docs-toolbar">
        <span className="docs-toolbar-hint">
          {editing
            ? 'Markdown'
            : currentApp.status === 'published'
              ? `Edits apply now and are saved with v${currentApp.version + 1} on next publish.`
              : 'Saved with the pipeline and each published version.'}
        </span>
        <div className="docs-toolbar-actions">
          {(editing || saved.trim()) && (
            <button type="button" className="docs-btn" onClick={generate} disabled={generating || saving}>
              {generateLabel}
            </button>
          )}
          {editing ? (
            <>
              <button type="button" className="docs-btn" onClick={cancel} disabled={saving}>Cancel</button>
              <button type="button" className="docs-btn docs-btn--primary" onClick={save} disabled={saving || !dirty}>
                {saving ? 'Saving…' : 'Save'}
              </button>
            </>
          ) : saved.trim() && (
            <button type="button" className="docs-btn docs-btn--primary" onClick={() => setDraft(saved)}>Edit</button>
          )}
        </div>
      </div>

      {note && <p className="docs-note">{note}</p>}
      {error && <p className="docs-error">{error}</p>}

      {editing ? (
        <textarea
          className="docs-editor"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={'# Pipeline name\n\n## Overview\nWhat it does and who it is for.\n\n## Setup\n- …'}
          spellCheck
        />
      ) : saved.trim() ? (
        <div className="docs-rendered">{renderMarkdownBlock(saved)}</div>
      ) : (
        <div className="docs-empty">
          <p className="docs-empty-title">No docs yet</p>
          <p className="docs-empty-sub">
            Explain what this pipeline does, what it needs, and how to use it. Docs travel with published
            versions, Marketplace listings and the README export.
          </p>
          <div className="docs-empty-actions">
            <button type="button" className="docs-btn docs-btn--primary" onClick={generate} disabled={generating}>
              {generateLabel}
            </button>
            <button type="button" className="docs-btn" onClick={() => setDraft('')}>Write manually</button>
          </div>
        </div>
      )}
    </div>
  )
}
