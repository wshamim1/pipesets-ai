import { useCallback, useEffect, useMemo, useState } from 'react'
import { API_BASE } from '../../types'
import type { AppRecord } from '../../types'
import { fetchAppVersions } from '../../utils/publishedApps'
import type { AppVersionInfo } from '../../utils/publishedApps'
import { AiCaseGenerator } from './AiCaseGenerator'
import { onDownload } from '../../utils/download'
import type { DatasetRef } from './AiCaseGenerator'

export interface EvalDatasetRow extends DatasetRef {
  description: string
  case_count: number
  ai_count: number
  created_at: string
}

interface EvalCase {
  id: string
  prompt: string
  expected_output: string
  tags: string[]
  source: 'manual' | 'ai' | 'traces'
  created_at: string
}

interface Props {
  dataset: EvalDatasetRow
  datasets: EvalDatasetRow[]
  apps: AppRecord[]
  /** Dataset list needs refreshing (counts, name, link changed). */
  onChanged: () => void
  onRun: () => void
}

type Panel = null | 'add' | 'more' | 'regenerate' | 'settings' | 'import'
const TAGS = ['happy_path', 'tool_use', 'edge_case', 'adversarial']

/** Cases of one dataset: search, filter, inline edit, bulk delete, AI generate / regenerate. */
export function DatasetDetail({ dataset, datasets, apps, onChanged, onRun }: Props) {
  const [cases, setCases] = useState<EvalCase[]>([])
  const [loading, setLoading] = useState(false)
  const [panel, setPanel] = useState<Panel>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [tagFilter, setTagFilter] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [editing, setEditing] = useState<{ id: string; prompt: string; expected: string } | null>(null)
  const [newCase, setNewCase] = useState({ prompt: '', expected: '' })

  const loadCases = useCallback(async () => {
    setLoading(true)
    try {
      const r = await fetch(`${API_BASE}/api/eval/datasets/${dataset.id}/cases`)
      setCases(r.ok ? await r.json() : [])
    } catch { setCases([]) }
    finally { setLoading(false) }
  }, [dataset.id])

  useEffect(() => {
    setSelected(new Set())
    setEditing(null)
    setPanel(null)
    loadCases()
  }, [loadCases])

  const flash = (text: string) => {
    setMsg(text)
    setTimeout(() => setMsg(null), 4000)
  }

  const refresh = async () => {
    await loadCases()
    onChanged()
  }

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return cases.filter((c) =>
      (!tagFilter || (tagFilter === 'ai' ? c.source === 'ai' : tagFilter === 'manual' ? c.source !== 'ai' : c.tags.includes(tagFilter)))
      && (!q || c.prompt.toLowerCase().includes(q) || c.expected_output.toLowerCase().includes(q)))
  }, [cases, query, tagFilter])

  const tagCounts = useMemo(() => {
    const out: Record<string, number> = { ai: 0, manual: 0 }
    for (const c of cases) {
      out[c.source === 'ai' ? 'ai' : 'manual'] += 1
      for (const t of c.tags) out[t] = (out[t] ?? 0) + 1
    }
    return out
  }, [cases])

  const allVisibleSelected = visible.length > 0 && visible.every((c) => selected.has(c.id))
  const toggleAll = () => setSelected(allVisibleSelected ? new Set() : new Set(visible.map((c) => c.id)))
  const toggle = (id: string) => setSelected((prev) => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })

  const deleteIds = async (ids: string[]) => {
    if (!ids.length) return
    if (ids.length > 1 && !window.confirm(`Delete ${ids.length} cases?`)) return
    await fetch(`${API_BASE}/api/eval/datasets/${dataset.id}/cases/delete`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids }),
    })
    setSelected((prev) => new Set([...prev].filter((id) => !ids.includes(id))))
    await refresh()
  }

  const saveEdit = async () => {
    if (!editing || !editing.prompt.trim()) return
    const r = await fetch(`${API_BASE}/api/eval/cases/${editing.id}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: editing.prompt, expected_output: editing.expected }),
    })
    if (r.ok) {
      const updated: EvalCase = await r.json()
      setCases((prev) => prev.map((c) => (c.id === updated.id ? updated : c)))
      setEditing(null)
    }
  }

  const addCase = async () => {
    if (!newCase.prompt.trim()) return
    await fetch(`${API_BASE}/api/eval/datasets/${dataset.id}/cases`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: newCase.prompt.trim(), expected_output: newCase.expected.trim(), tags: [] }),
    })
    setNewCase({ prompt: '', expected: '' })
    setPanel(null)
    await refresh()
  }

  const fromTraces = async () => {
    const r = await fetch(`${API_BASE}/api/eval/generate-from-traces`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dataset_id: dataset.id, app_id: dataset.app_id, limit: 20 }),
    })
    const d = await r.json().catch(() => ({}))
    await refresh()
    flash(r.ok ? `✓ Added ${d.cases_created ?? 0} cases from trace history` : '⚠ Could not read traces')
  }

  return (
    <div className="eval-cases-section">
      <div className="eval-cases-toolbar ds-toolbar">
        <button type="button" className="eval-action-btn" onClick={() => setPanel(panel === 'add' ? null : 'add')}>+ Add case</button>
        <button type="button" className="eval-action-btn eval-action-btn--generate" onClick={() => setPanel(panel === 'more' ? null : 'more')}>
          ✨ Generate more
        </button>
        <button
          type="button" className="eval-action-btn" disabled={!dataset.ai_count}
          title={dataset.ai_count ? 'Replace the AI-generated cases with a fresh set' : 'No AI cases to regenerate'}
          onClick={() => setPanel(panel === 'regenerate' ? null : 'regenerate')}
        >↻ Regenerate</button>
        <button type="button" className="eval-action-btn" onClick={fromTraces} title="Add cases from past prompts">⚡ From traces</button>
        <button type="button" className="eval-action-btn" onClick={() => setPanel(panel === 'import' ? null : 'import')} title="Upload cases from Excel or CSV">⬆ Import</button>
        <span className="ds-export">
          <button type="button" className="eval-action-btn" onClick={onDownload(`${API_BASE}/api/eval/datasets/${dataset.id}/export?format=xlsx`, `${dataset.name}.xlsx`)} title="Download cases as Excel">⬇ Excel</button>
          <button type="button" className="eval-action-btn" onClick={onDownload(`${API_BASE}/api/eval/datasets/${dataset.id}/export?format=csv`, `${dataset.name}.csv`)} title="Download cases as CSV">CSV</button>
        </span>
        <button type="button" className="eval-action-btn" onClick={() => setPanel(panel === 'settings' ? null : 'settings')}>⚙ Settings</button>
        <span className="ds-toolbar-spacer" />
        <button type="button" className="eval-action-btn eval-action-btn--primary" disabled={!cases.length} onClick={onRun}>▶ Run</button>
      </div>

      {msg && <div className={`eval-generate-msg${msg.startsWith('⚠') ? ' eval-generate-msg--warn' : ''}`}>{msg}</div>}

      {panel === 'add' && (
        <div className="eval-form-card">
          <textarea placeholder="Prompt / test input" className="eval-textarea" rows={3}
            value={newCase.prompt} onChange={(e) => setNewCase({ ...newCase, prompt: e.target.value })} />
          <input type="text" placeholder="Expected output (optional — used for scoring)" className="eval-input"
            value={newCase.expected} onChange={(e) => setNewCase({ ...newCase, expected: e.target.value })} />
          <div className="eval-form-actions">
            <button type="button" className="eval-save-btn" onClick={addCase} disabled={!newCase.prompt.trim()}>Add</button>
            <button type="button" className="eval-cancel-btn" onClick={() => setPanel(null)}>Cancel</button>
          </div>
        </div>
      )}

      {(panel === 'more' || panel === 'regenerate') && (
        <AiCaseGenerator
          key={panel}
          apps={apps}
          datasets={datasets}
          dataset={dataset}
          mode={panel}
          onClose={() => setPanel(null)}
          onSaved={async (_, message) => {
            setPanel(null)
            await refresh()
            flash(message)
          }}
        />
      )}

      {panel === 'import' && (
        <ImportPanel
          datasetId={dataset.id}
          onDone={async (message) => { setPanel(null); await refresh(); flash(message) }}
          onCancel={() => setPanel(null)}
        />
      )}

      {panel === 'settings' && (
        <DatasetSettings dataset={dataset} apps={apps} onSaved={() => { setPanel(null); onChanged() }} onCancel={() => setPanel(null)} />
      )}

      {cases.length > 0 && (
        <div className="ds-filter-row">
          <input type="search" className="eval-input ds-search" placeholder="Search cases…" value={query} onChange={(e) => setQuery(e.target.value)} />
          <div className="ds-chips">
            <button type="button" className={`ds-chip${!tagFilter ? ' ds-chip--on' : ''}`} onClick={() => setTagFilter(null)}>All {cases.length}</button>
            {['ai', 'manual', ...TAGS].filter((t) => tagCounts[t]).map((t) => (
              <button key={t} type="button" className={`ds-chip${tagFilter === t ? ' ds-chip--on' : ''}`} onClick={() => setTagFilter(tagFilter === t ? null : t)}>
                {t === 'ai' ? '✨ AI' : t.replace('_', ' ')} {tagCounts[t]}
              </button>
            ))}
          </div>
        </div>
      )}

      {cases.length > 0 && (
        <div className="ds-bulk-row">
          <label className="ds-check-all">
            <input type="checkbox" checked={allVisibleSelected} onChange={toggleAll} />
            {selected.size ? `${selected.size} selected` : 'Select'}
          </label>
          {selected.size > 0 && (
            <button type="button" className="ds-danger-btn" onClick={() => deleteIds([...selected])}>Delete selected</button>
          )}
          {visible.length !== cases.length && <span className="eval-label">Showing {visible.length} of {cases.length}</span>}
        </div>
      )}

      {loading && <div className="eval-empty">Loading cases…</div>}
      {!loading && cases.length === 0 && (
        <div className="eval-empty">No cases yet. Use ✨ Generate more, add one manually, or pull from traces.</div>
      )}

      <div className="eval-case-list">
        {visible.map((c, i) => (
          <div key={c.id} className={`eval-case-row ds-case-row${selected.has(c.id) ? ' ds-case-row--selected' : ''}`}>
            <input type="checkbox" checked={selected.has(c.id)} onChange={() => toggle(c.id)} />
            <div className="eval-case-num">#{i + 1}</div>
            {editing?.id === c.id ? (
              <div className="eval-case-content ds-edit">
                <textarea className="eval-textarea" rows={2} autoFocus value={editing.prompt}
                  onChange={(e) => setEditing({ ...editing, prompt: e.target.value })} />
                <input type="text" className="eval-input" placeholder="Expected output (optional)" value={editing.expected}
                  onChange={(e) => setEditing({ ...editing, expected: e.target.value })}
                  onKeyDown={(e) => { if (e.key === 'Enter') saveEdit(); if (e.key === 'Escape') setEditing(null) }} />
                <div className="eval-form-actions">
                  <button type="button" className="eval-save-btn" disabled={!editing.prompt.trim()} onClick={saveEdit}>Save</button>
                  <button type="button" className="eval-cancel-btn" onClick={() => setEditing(null)}>Cancel</button>
                </div>
              </div>
            ) : (
              <div className="eval-case-content" onDoubleClick={() => setEditing({ id: c.id, prompt: c.prompt, expected: c.expected_output })}>
                <div className="eval-case-prompt">{c.prompt}</div>
                {c.expected_output && (
                  <div className="eval-case-expected">Expected: {c.expected_output.slice(0, 160)}{c.expected_output.length > 160 ? '…' : ''}</div>
                )}
                <div className="ai-gen-tags">
                  <span className={`ds-source ds-source--${c.source}`}>{c.source === 'ai' ? '✨ AI' : c.source}</span>
                  {c.tags.map((t) => <span key={t} className={`ai-gen-tag ai-gen-tag--${t}`}>{t.replace('_', ' ')}</span>)}
                </div>
              </div>
            )}
            {editing?.id !== c.id && (
              <div className="ds-row-actions">
                <button type="button" className="ds-icon-btn" title="Edit" onClick={() => setEditing({ id: c.id, prompt: c.prompt, expected: c.expected_output })}>✎</button>
                <button type="button" className="eval-del-btn" title="Delete" onClick={() => deleteIds([c.id])}>✕</button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function DatasetSettings({ dataset, apps, onSaved, onCancel }: {
  dataset: EvalDatasetRow
  apps: AppRecord[]
  onSaved: () => void
  onCancel: () => void
}) {
  const [name, setName] = useState(dataset.name)
  const [description, setDescription] = useState(dataset.description)
  const [appId, setAppId] = useState(dataset.app_id ?? '')
  const [version, setVersion] = useState(dataset.app_version ?? 0)
  const [versions, setVersions] = useState<AppVersionInfo[]>([])

  useEffect(() => {
    setVersions([])
    if (!appId) return
    fetchAppVersions(appId).then(setVersions).catch(() => setVersions([]))
  }, [appId])

  const save = async () => {
    const r = await fetch(`${API_BASE}/api/eval/datasets/${dataset.id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name.trim(), description: description.trim(), app_id: appId, app_version: version }),
    })
    if (r.ok) onSaved()
  }

  return (
    <div className="eval-form-card">
      <div className="ai-gen-row">
        <label className="eval-field">
          <span className="eval-label">Name</span>
          <input type="text" className="eval-input" value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="eval-field">
          <span className="eval-label">Pipeline</span>
          <select className="eval-select" value={appId} onChange={(e) => { setAppId(e.target.value); setVersion(0) }}>
            <option value="">Not linked</option>
            {apps.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </label>
        <label className="eval-field">
          <span className="eval-label">Version</span>
          <select className="eval-select" value={version} disabled={!appId} onChange={(e) => setVersion(Number(e.target.value))}>
            {versions.map((v) => <option key={v.version} value={v.version}>v{v.version}{v.version === versions[0]?.version ? ' (latest)' : ''}</option>)}
            <option value={0}>Saved draft</option>
          </select>
        </label>
      </div>
      <input type="text" className="eval-input" placeholder="Description" value={description} onChange={(e) => setDescription(e.target.value)} />
      <div className="eval-form-actions">
        <button type="button" className="eval-save-btn" disabled={!name.trim()} onClick={save}>Save</button>
        <button type="button" className="eval-cancel-btn" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  )
}


function ImportPanel({ datasetId, onDone, onCancel }: {
  datasetId: string
  onDone: (message: string) => void
  onCancel: () => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [replace, setReplace] = useState<'none' | 'all'>('none')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const upload = async () => {
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('replace', replace)
      const r = await fetch(`${API_BASE}/api/eval/datasets/${datasetId}/import`, { method: 'POST', body: form })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { setError(typeof d.detail === 'string' ? d.detail : r.statusText); return }
      const cols = Object.entries(d.columns ?? {}).map(([k, v]) => `${k} ← "${v}"`).join(', ')
      const parts = [`✓ Imported ${d.cases_created} case${d.cases_created === 1 ? '' : 's'}`]
      if (d.replaced) parts.push(`replaced ${d.replaced}`)
      if (d.skipped_duplicates) parts.push(`skipped ${d.skipped_duplicates} duplicate${d.skipped_duplicates === 1 ? '' : 's'}`)
      if (d.empty_rows) parts.push(`${d.empty_rows} row${d.empty_rows === 1 ? '' : 's'} without a prompt`)
      onDone(`${parts.join(' · ')}${cols ? ` (${cols})` : ''}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="eval-form-card">
      <div className="eval-label">
        Upload an <strong>.xlsx</strong> or <strong>.csv</strong>. The first sheet is read; columns are matched by header —
        <em> prompt / input / question</em>, <em>expected / answer</em>, <em>tags / category</em> — or A, B, C without a header.
        Template:{' '}
        <button type="button" className="link-btn" onClick={onDownload(`${API_BASE}/api/eval/import-template?format=xlsx`, 'eval_cases_template.xlsx')}>Excel</button>
        {' · '}
        <button type="button" className="link-btn" onClick={onDownload(`${API_BASE}/api/eval/import-template?format=csv`, 'eval_cases_template.csv')}>CSV</button>
      </div>
      <input type="file" accept=".xlsx,.xlsm,.csv,.tsv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      <div className="ds-radio-row">
        <label><input type="radio" checked={replace === 'none'} onChange={() => setReplace('none')} /> Add to existing cases (duplicates skipped)</label>
        <label><input type="radio" checked={replace === 'all'} onChange={() => setReplace('all')} /> Replace all cases</label>
      </div>
      {error && <div className="eval-generate-msg eval-generate-msg--warn">⚠ {error}</div>}
      <div className="eval-form-actions">
        <button type="button" className="eval-save-btn" disabled={!file || busy} onClick={upload}>{busy ? 'Importing…' : '⬆ Import'}</button>
        <button type="button" className="eval-cancel-btn" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  )
}
