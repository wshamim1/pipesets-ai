import { useCallback, useEffect, useState } from 'react'
import { API_BASE } from '../../types'

type Scope = 'project' | 'workspace'

interface SettingRow { backend: string; base_url: string; updated_by: string; updated_at: string }

interface ProviderSetting {
  id: string
  name: string
  local: boolean
  backends: string[]
  default_base_url: string
  project: SettingRow | null
  workspace: SettingRow | null
  effective: {
    backend: string
    backend_source: string
    base_url: string
    base_url_source: string
    serving_backend: string | null
  }
}

interface SettingsPayload {
  can_edit: boolean
  backends: { id: string; label: string }[]
  providers: ProviderSetting[]
}

interface Draft { backend: string; base_url: string }

type TestState = { status: 'testing' } | { status: 'ok' | 'error'; message: string; backend: string; latencyMs: number; model: string }
type MigrateResult = { scope: Scope; dry_run: boolean; updated_count: number; updated: Array<{ provider: string }> }

const SOURCE_LABELS: Record<string, string> = {
  project: 'set for this project',
  workspace: 'set for the workspace',
  default: 'default',
}

const sourceLabel = (source: string) =>
  source.startsWith('env:') ? `server setting ${source.slice(4)}` : SOURCE_LABELS[source] ?? source

async function errorText(res: Response): Promise<string> {
  try {
    const body = await res.json()
    return typeof body?.detail === 'string' ? body.detail : `HTTP ${res.status}`
  } catch {
    return `HTTP ${res.status}`
  }
}

async function fetchSettings(): Promise<SettingsPayload> {
  const res = await fetch(`${API_BASE}/api/llm-settings`)
  if (!res.ok) throw new Error(await errorText(res))
  return res.json()
}

/** Settings → Model backends: which engine sends each provider's model calls, and its base URL. */
export function ModelBackendsPanel() {
  const [data, setData] = useState<SettingsPayload | null>(null)
  const [loadError, setLoadError] = useState('')
  const [scope, setScope] = useState<Scope>('project')
  const [drafts, setDrafts] = useState<Record<string, Draft>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [rowError, setRowError] = useState<Record<string, string>>({})
  const [tests, setTests] = useState<Record<string, TestState>>({})
  const [migrateMsg, setMigrateMsg] = useState('')

  const applyLoad = useCallback((p: Promise<SettingsPayload>, isCurrent: () => boolean = () => true) =>
    p.then(
      (d) => { if (isCurrent()) { setData(d); setLoadError('') } },
      (e) => { if (isCurrent()) setLoadError(e instanceof Error ? e.message : String(e)) },
    ), [])
  const load = useCallback(() => applyLoad(fetchSettings()), [applyLoad])

  useEffect(() => {
    let current = true
    void applyLoad(fetchSettings(), () => current)
    return () => { current = false }
  }, [applyLoad])

  const backendLabel = (id: string | null) =>
    id ? data?.backends.find((b) => b.id === id)?.label ?? id : 'none available'

  const saved = (p: ProviderSetting): Draft => {
    const row = scope === 'project' ? p.project : p.workspace
    return { backend: row?.backend ?? 'auto', base_url: row?.base_url ?? '' }
  }
  const draftFor = (p: ProviderSetting): Draft => drafts[p.id] ?? saved(p)
  const isDirty = (p: ProviderSetting) => {
    const d = draftFor(p), s = saved(p)
    return d.backend !== s.backend || d.base_url.trim() !== s.base_url
  }
  const setDraft = (p: ProviderSetting, patch: Partial<Draft>) =>
    setDrafts((prev) => ({ ...prev, [p.id]: { ...draftFor(p), ...patch } }))
  const dropDraft = (id: string) =>
    setDrafts((prev) => { const next = { ...prev }; delete next[id]; return next })

  const switchScope = (next: Scope) => {
    setScope(next)
    setDrafts({})
    setRowError({})
    setMigrateMsg('')
  }

  const migrateLiteLLM = async () => {
    setBusy('__migrate__')
    setMigrateMsg('')
    try {
      const res = await fetch(`${API_BASE}/api/llm-settings/migrate-litellm?scope=${scope}`, { method: 'POST' })
      if (!res.ok) throw new Error(await errorText(res))
      const body = await res.json() as MigrateResult
      setMigrateMsg(body.updated_count > 0
        ? `Migrated ${body.updated_count} provider override(s) from LiteLLM to automatic adapters.`
        : 'No LiteLLM overrides needed migration in this scope.')
      await load()
    } catch (e) {
      setMigrateMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  const save = async (p: ProviderSetting) => {
    const d = draftFor(p)
    setBusy(p.id)
    setRowError((prev) => ({ ...prev, [p.id]: '' }))
    try {
      const res = await fetch(`${API_BASE}/api/llm-settings/${p.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ backend: d.backend, base_url: d.base_url.trim(), scope }),
      })
      if (!res.ok) throw new Error(await errorText(res))
      dropDraft(p.id)
      await load()
    } catch (e) {
      setRowError((prev) => ({ ...prev, [p.id]: e instanceof Error ? e.message : String(e) }))
    } finally {
      setBusy(null)
    }
  }

  const reset = async (p: ProviderSetting) => {
    setBusy(p.id)
    setRowError((prev) => ({ ...prev, [p.id]: '' }))
    try {
      const res = await fetch(`${API_BASE}/api/llm-settings/${p.id}?scope=${scope}`, { method: 'DELETE' })
      if (!res.ok) throw new Error(await errorText(res))
      dropDraft(p.id)
      await load()
    } catch (e) {
      setRowError((prev) => ({ ...prev, [p.id]: e instanceof Error ? e.message : String(e) }))
    } finally {
      setBusy(null)
    }
  }

  // Tests what the row currently shows (unsaved edits included)
  const test = async (p: ProviderSetting) => {
    const d = draftFor(p)
    setTests((prev) => ({ ...prev, [p.id]: { status: 'testing' } }))
    try {
      const res = await fetch(`${API_BASE}/api/llm-settings/${p.id}/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          backend: d.backend === 'auto' ? null : d.backend,
          base_url: d.base_url.trim() || null,
        }),
      })
      if (!res.ok) throw new Error(await errorText(res))
      const r = await res.json()
      setTests((prev) => ({
        ...prev,
        [p.id]: { status: r.ok ? 'ok' : 'error', message: r.message, backend: r.backend, latencyMs: r.latency_ms, model: r.model },
      }))
    } catch (e) {
      setTests((prev) => ({
        ...prev,
        [p.id]: { status: 'error', message: e instanceof Error ? e.message : String(e), backend: '', latencyMs: 0, model: '' },
      }))
    }
  }

  const renderTest = (id: string) => {
    const t = tests[id]
    if (!t) return null
    if (t.status === 'testing') return <span className="tnav-key-badge tnav-key-badge--testing">Testing…</span>
    const via = t.backend ? ` via ${backendLabel(t.backend)}` : ''
    if (t.status === 'ok') {
      return <span className="tnav-key-badge tnav-key-badge--ok" title={`${t.model}: ${t.message}`}>OK · {t.latencyMs}ms{via}</span>
    }
    return <span className="tnav-key-badge tnav-key-badge--err" title={t.message}>{t.message}</span>
  }

  if (loadError) {
    return <div className="settings-card"><p className="settings-card-hint" style={{ color: '#b91c1c' }}>Couldn't load model backends: {loadError}</p></div>
  }
  if (!data) {
    return <div className="settings-card"><p className="settings-card-hint">Loading…</p></div>
  }

  const editable = data.can_edit
  const nativeCapableCount = data.providers.filter((p) => p.backends.some((b) => b !== 'litellm')).length
  const liteOnlyCount = data.providers.length - nativeCapableCount
  const currentlyLiteCount = data.providers.filter((p) => p.effective.serving_backend === 'litellm').length

  return (
    <div className="settings-card">
      <div className="settings-card-header">
        <p className="settings-card-hint">
          Which engine sends each provider's model calls, and where. A project setting beats the
          workspace setting, which beats the server's own defaults; a model node's base URL beats
          them all. Every run's trace records the engine that served it.
          {!editable && ' You can view these settings; changing them needs write access to secrets.'}
        </p>
        <div className="backends-scope" role="group" aria-label="Edit settings for">
          {(['project', 'workspace'] as Scope[]).map((s) => (
            <button key={s} type="button"
              className={`backends-scope-btn${scope === s ? ' backends-scope-btn--active' : ''}`}
              aria-pressed={scope === s} onClick={() => switchScope(s)}>
              {s === 'project' ? 'This project' : 'Whole workspace'}
            </button>
          ))}
          {editable && (
            <button type="button" className="ops-refresh-btn" onClick={migrateLiteLLM}
              disabled={busy === '__migrate__'}>
              {busy === '__migrate__' ? 'Migrating…' : 'Migrate LiteLLM overrides'}
            </button>
          )}
        </div>
      </div>
      {migrateMsg && <p className="settings-card-hint">{migrateMsg}</p>}
      <div className="backends-coverage">
        <span className="backends-coverage-chip backends-coverage-chip--native">Native-capable: {nativeCapableCount}</span>
        <span className="backends-coverage-chip backends-coverage-chip--lite">LiteLLM-only: {liteOnlyCount}</span>
        <span className="backends-coverage-chip">Currently on LiteLLM: {currentlyLiteCount}</span>
      </div>

      <div className="backends-list">
        <div className="backends-row backends-row--head" aria-hidden="true">
          <span>Provider</span><span>Engine</span><span>Base URL</span><span /><span />
        </div>
        {data.providers.map((p) => {
          const d = draftFor(p)
          const row = scope === 'project' ? p.project : p.workspace
          const dirty = isDirty(p)
          const eff = p.effective
          const nativeCapable = p.backends.some((b) => b !== 'litellm')
          const usingLite = eff.serving_backend === 'litellm'
          // What the unset option resolves to, named by where it comes from; only knowable while this project sets no engine
          const inherited = scope === 'project' && (!row || row.backend === 'auto') ? eff.serving_backend : null
          return (
            <div key={p.id} className="backends-item">
              <div className="backends-row">
                <span className="settings-key-label">
                  {p.name}{p.local && <span className="backends-local-chip">local</span>}
                  <span className={`backends-status-chip ${nativeCapable ? 'backends-status-chip--native' : 'backends-status-chip--lite'}`}>
                    {nativeCapable ? 'native-capable' : 'litellm-only'}
                  </span>
                </span>
                <select className="ops-select" aria-label={`${p.name} engine`} value={d.backend}
                  disabled={!editable || busy === p.id} onChange={(e) => setDraft(p, { backend: e.target.value })}>
                  <option value="auto">
                    {scope === 'project'
                      ? (inherited
                          ? `${eff.backend_source === 'workspace' ? 'Workspace' : eff.backend_source.startsWith('env:') ? 'Server (.env)' : 'Automatic'}: ${backendLabel(inherited)}`
                          : 'Workspace or automatic')
                      : 'Automatic'}
                  </option>
                  {p.backends.map((b) => <option key={b} value={b}>{backendLabel(b)}</option>)}
                </select>
                <input className="settings-key-input" aria-label={`${p.name} base URL`} value={d.base_url}
                  placeholder={p.default_base_url || 'provider default'} spellCheck={false}
                  disabled={!editable || busy === p.id}
                  onChange={(e) => setDraft(p, { base_url: e.target.value })}
                  onKeyDown={(e) => { if (e.key === 'Enter' && dirty) void save(p) }} />
                <span className="settings-key-actions">
                  {editable && dirty && (
                    <>
                      <button type="button" className="ops-refresh-btn" onClick={() => save(p)} disabled={busy === p.id}>
                        {busy === p.id ? 'Saving…' : 'Save'}
                      </button>
                      <button type="button" className="ops-link-btn" onClick={() => dropDraft(p.id)}>Cancel</button>
                    </>
                  )}
                  {editable && !dirty && row && (
                    <button type="button" className="ops-link-btn" onClick={() => reset(p)} disabled={busy === p.id}>Reset</button>
                  )}
                </span>
                <span className="backends-test">
                  <button type="button" className="ops-refresh-btn" onClick={() => test(p)}
                    disabled={tests[p.id]?.status === 'testing'}>Test</button>
                  {renderTest(p.id)}
                </span>
              </div>
              <div className="backends-effective">
                In effect: <strong>{backendLabel(eff.serving_backend)}</strong>
                {eff.backend === 'auto' ? ' (automatic)' : ''} · {sourceLabel(eff.backend_source)}
                {eff.base_url && <> · <code>{eff.base_url}</code> ({sourceLabel(eff.base_url_source)})</>}
                {usingLite && nativeCapable && <> · <span className="backends-warning">using LiteLLM despite native adapter availability</span></>}
              </div>
              {rowError[p.id] && <div className="backends-error">{rowError[p.id]}</div>}
            </div>
          )
        })}
      </div>
    </div>
  )
}
