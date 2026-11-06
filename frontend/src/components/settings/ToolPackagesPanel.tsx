import { useCallback, useEffect, useMemo, useState } from 'react'
import { API_BASE } from '../../types'
import type { ToolCatalogItem, ToolCategory } from '../../types'

type Kind = 'tool' | 'mcp'
type Show = 'all' | 'installed' | 'available'

interface PackageState {
  id: string
  installed: boolean
  /** Why it is installed or not: an explicit choice, the default set, or a pipeline using it */
  source: 'choice' | 'default' | 'in_use' | null
  in_use: boolean
  default: boolean
}

interface Package extends PackageState {
  item: ToolCatalogItem
  kind: Kind
}

async function errorText(res: Response): Promise<string> {
  try {
    const body = await res.json()
    return typeof body?.detail === 'string' ? body.detail : `HTTP ${res.status}`
  } catch {
    return `HTTP ${res.status}`
  }
}

interface ReloadResult {
  changed: boolean
  modules: number
  added: string[]
  removed: string[]
  errors: { module: string; error: string }[]
  note?: string
}

function reloadSummary(r: ReloadResult): string {
  if (r.note) return r.note
  if (!r.changed) return 'No changes on disk since the last load.'
  const parts = [`Reloaded ${r.modules} module${r.modules === 1 ? '' : 's'}`]
  if (r.added.length) parts.push(`new: ${r.added.join(', ')}`)
  if (r.removed.length) parts.push(`removed: ${r.removed.join(', ')}`)
  return parts.join(' · ') + '.'
}

async function fetchPackages(): Promise<{ canEdit: boolean; canReload: boolean; packages: Package[] }> {
  const [catalogRes, packagesRes] = await Promise.all([
    fetch(`${API_BASE}/api/tools`),
    fetch(`${API_BASE}/api/tools/packages`),
  ])
  if (!catalogRes.ok) throw new Error(await errorText(catalogRes))
  if (!packagesRes.ok) throw new Error(await errorText(packagesRes))
  const categories: ToolCategory[] = (await catalogRes.json()).categories ?? []
  const { can_edit, can_reload, packages } = await packagesRes.json() as { can_edit: boolean; can_reload?: boolean; packages: PackageState[] }
  const items = new Map(categories.filter((c) => c.id !== 'frameworks').flatMap((c) => c.tools).map((t) => [t.id, t]))
  return {
    canEdit: can_edit,
    canReload: Boolean(can_reload),
    packages: packages.flatMap((p) => {
      const item = items.get(p.id)
      return item ? [{ ...p, item, kind: item.type === 'mcp' ? 'mcp' as const : 'tool' as const }] : []
    }),
  }
}

const SOURCE_LABEL: Record<string, string> = {
  default: 'Default',
  in_use: 'Used in a pipeline',
}

/** Settings → Tools & MCP packages: install built-in tools and MCP servers to offer them as nodes in the builder. */
export function ToolPackagesPanel({ onChanged }: { onChanged?: () => void }) {
  const [packages, setPackages] = useState<Package[] | null>(null)
  const [canEdit, setCanEdit] = useState(false)
  const [canReload, setCanReload] = useState(false)
  const [reloadResult, setReloadResult] = useState<ReloadResult | null>(null)
  const [loadError, setLoadError] = useState('')
  const [actionError, setActionError] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [kind, setKind] = useState<Kind>('tool')
  const [show, setShow] = useState<Show>('all')
  const [category, setCategory] = useState('')
  const [query, setQuery] = useState('')
  // Categories the user opened; a search or a picked category opens every group that matches
  const [openGroups, setOpenGroups] = useState<Set<string>>(() => new Set())

  const applyLoad = useCallback((p: ReturnType<typeof fetchPackages>, isCurrent: () => boolean = () => true) =>
    p.then(
      (d) => { if (isCurrent()) { setPackages(d.packages); setCanEdit(d.canEdit); setCanReload(d.canReload); setLoadError('') } },
      (e) => { if (isCurrent()) setLoadError(e instanceof Error ? e.message : String(e)) },
    ), [])
  const load = useCallback(() => applyLoad(fetchPackages()), [applyLoad])

  useEffect(() => {
    let current = true
    void applyLoad(fetchPackages(), () => current)
    return () => { current = false }
  }, [applyLoad])

  const ofKind = useMemo(() => (packages ?? []).filter((p) => p.kind === kind), [packages, kind])
  const categories = useMemo(() => [...new Set(ofKind.map((p) => p.item.category || 'Other'))], [ofKind])
  const q = query.trim().toLowerCase()
  const matches = (p: Package) => (show === 'all' || (show === 'installed') === p.installed)
    && (!q || [p.item.name, p.item.description, p.item.id, p.item.category].some((f) => f?.toLowerCase().includes(q)))
  const shown = ofKind.filter((p) => matches(p) && (!category || (p.item.category || 'Other') === category))
  // A search also counts the other tab, so "cloudflare" under Tools points to MCP servers
  const otherKind: Kind = kind === 'tool' ? 'mcp' : 'tool'
  const matchCount = (k: Kind) => (packages ?? []).filter((p) => p.kind === k && matches(p)).length
  const groups = categories
    .map((name) => ({ name, items: shown.filter((p) => (p.item.category || 'Other') === name) }))
    .filter((g) => g.items.length > 0)
  const installedCount = ofKind.filter((p) => p.installed).length
  const autoOpen = q !== '' || category !== ''
  const isOpen = (name: string) => autoOpen || openGroups.has(name)
  const toggleGroup = (name: string) => setOpenGroups((prev) => {
    const next = new Set(prev)
    if (next.has(name)) next.delete(name)
    else next.add(name)
    return next
  })
  const allOpen = groups.length > 0 && groups.every((g) => isOpen(g.name))

  const change = async (ids: string[], installed: boolean, key: string) => {
    if (ids.length === 0) return
    setBusy(key)
    setActionError('')
    try {
      const res = await fetch(`${API_BASE}/api/tools/packages`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tool_ids: ids, installed }),
      })
      if (!res.ok) throw new Error(await errorText(res))
      const updated = new Map(((await res.json()).packages as PackageState[]).map((p) => [p.id, p]))
      setPackages((prev) => prev && prev.map((p) => (updated.has(p.id) ? { ...p, ...updated.get(p.id)! } : p)))
      onChanged?.()
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  const resetAll = async () => {
    if (!window.confirm('Forget every install and uninstall in this workspace? The default set, plus anything your pipelines use, will be installed again.')) return
    setBusy('__reset__')
    setActionError('')
    try {
      const res = await fetch(`${API_BASE}/api/tools/packages`, { method: 'DELETE' })
      if (!res.ok) throw new Error(await errorText(res))
      await load()
      onChanged?.()
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  const reloadFromDisk = async () => {
    setBusy('__reload__')
    setActionError('')
    setReloadResult(null)
    try {
      const res = await fetch(`${API_BASE}/api/tools/reload`, { method: 'POST' })
      if (!res.ok) throw new Error(await errorText(res))
      const result = await res.json() as ReloadResult
      setReloadResult(result)
      if (result.changed) {
        await load()
        onChanged?.()
      }
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  if (loadError) {
    return <div className="settings-card"><p className="settings-card-hint" style={{ color: '#b91c1c' }}>Couldn't load packages: {loadError}</p></div>
  }
  if (!packages) {
    return <div className="settings-card"><p className="settings-card-hint">Loading…</p></div>
  }

  const notInstalledShown = shown.filter((p) => !p.installed).map((p) => p.id)

  return (
    <div className="settings-card">
      <div className="settings-card-header">
        <p className="settings-card-hint">
          Installed tools and MCP servers appear as nodes in the builder's sidebar; the rest wait here.
          Uninstalling only hides a package from the sidebar — pipelines that already use it keep working.
          {!canEdit && ' You can browse packages; installing them needs write access to tools.'}
        </p>
        <span className="pkg-summary-actions">
          {canReload && (
            <button type="button" className="ops-link-btn" onClick={reloadFromDisk} disabled={busy !== null}
              title="Pick up tools and MCP servers added or edited in backend/tools/ without restarting the backend">
              {busy === '__reload__' ? 'Reloading…' : 'Reload from disk'}
            </button>
          )}
          {canEdit && (
            <button type="button" className="ops-link-btn" onClick={resetAll} disabled={busy !== null}>
              Reset to defaults
            </button>
          )}
        </span>
      </div>
      {reloadResult && (
        <div className="pkg-reload-result" role="status">
          <span>{reloadSummary(reloadResult)}</span>
          {reloadResult.errors.length > 0 && (
            <ul className="backends-error">
              {reloadResult.errors.map((e) => <li key={e.module}><code>{e.module}</code>: {e.error}</li>)}
            </ul>
          )}
        </div>
      )}

      <div className="pkg-toolbar">
        <div className="backends-scope" role="group" aria-label="Package type">
          {(['tool', 'mcp'] as Kind[]).map((k) => (
            <button key={k} type="button"
              className={`backends-scope-btn${kind === k ? ' backends-scope-btn--active' : ''}`}
              aria-pressed={kind === k} onClick={() => { setKind(k); setCategory('') }}>
              {k === 'tool' ? 'Tools' : 'MCP servers'}{q ? ` (${matchCount(k)})` : ''}
            </button>
          ))}
        </div>
        <div className="backends-scope" role="group" aria-label="Show">
          {(['all', 'installed', 'available'] as Show[]).map((s) => (
            <button key={s} type="button"
              className={`backends-scope-btn${show === s ? ' backends-scope-btn--active' : ''}`}
              aria-pressed={show === s} onClick={() => setShow(s)}>
              {s === 'all' ? 'All' : s === 'installed' ? 'Installed' : 'Not installed'}
            </button>
          ))}
        </div>
        <input type="search" className="settings-key-input pkg-search" placeholder="Search packages…"
          aria-label="Search packages" value={query} onChange={(e) => setQuery(e.target.value)} />
        <select className="ops-select" aria-label="Category" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">All categories</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>

      <div className="pkg-summary">
        <span>{installedCount} of {ofKind.length} {kind === 'tool' ? 'tools' : 'MCP servers'} installed</span>
        <span className="pkg-summary-actions">
          {!autoOpen && groups.length > 0 && (
            <button type="button" className="ops-link-btn"
              onClick={() => setOpenGroups(allOpen ? new Set() : new Set(groups.map((g) => g.name)))}>
              {allOpen ? 'Collapse all' : 'Expand all'}
            </button>
          )}
          {canEdit && notInstalledShown.length > 0 && (
            <button type="button" className="ops-refresh-btn" disabled={busy !== null}
              onClick={() => change(notInstalledShown, true, '__bulk__')}>
              {busy === '__bulk__' ? 'Installing…' : `Install all ${notInstalledShown.length} matching`}
            </button>
          )}
        </span>
      </div>
      {actionError && <div className="backends-error">{actionError}</div>}

      {groups.length === 0 && (
        <p className="settings-card-hint">
          {q ? `No ${kind === 'tool' ? 'tools' : 'MCP servers'} match “${query.trim()}”${category ? ` in ${category}` : ''}.` : 'No packages match.'}
          {q && matchCount(otherKind) > 0 && (<>
            {' '}{matchCount(otherKind)} {otherKind === 'mcp' ? `MCP server${matchCount(otherKind) === 1 ? '' : 's'}` : `tool${matchCount(otherKind) === 1 ? '' : 's'}`} match{matchCount(otherKind) === 1 ? 'es' : ''} —{' '}
            <button type="button" className="ops-link-btn" onClick={() => { setKind(otherKind); setCategory('') }}>
              show {otherKind === 'mcp' ? 'MCP servers' : 'tools'}
            </button>
          </>)}
        </p>
      )}
      {groups.map((g) => (
        <section key={g.name} className="pkg-group" aria-label={g.name}>
          <h3 className="pkg-group-title">
            <button type="button" className="pkg-group-toggle" aria-expanded={isOpen(g.name)}
              disabled={autoOpen} onClick={() => toggleGroup(g.name)}>
              <span className="pkg-group-chevron" aria-hidden="true">{isOpen(g.name) ? '▾' : '▸'}</span>
              {g.name}
              <span className="pkg-group-count">
                {g.items.filter((p) => p.installed).length} / {g.items.length} installed
              </span>
            </button>
          </h3>
          {isOpen(g.name) && <div className="pkg-grid">
            {g.items.map((p) => (
              <div key={p.id} className={`pkg-card${p.installed ? ' pkg-card--installed' : ''}`}>
                <div className="pkg-card-head">
                  <span className="pkg-icon" aria-hidden="true">{p.item.icon}</span>
                  <span className="pkg-name">{p.item.name}</span>
                  {p.item.is_new && <span className="tool-icon-new">New</span>}
                </div>
                <p className="pkg-desc">{p.item.description}</p>
                <div className="pkg-card-foot">
                  <span className="pkg-badges">
                    {p.installed && p.source && SOURCE_LABEL[p.source] && <span className="pkg-badge">{SOURCE_LABEL[p.source]}</span>}
                    {p.in_use && p.source !== 'in_use' && <span className="pkg-badge">Used in a pipeline</span>}
                  </span>
                  {canEdit ? (
                    <button type="button" disabled={busy !== null}
                      className={p.installed ? 'ops-link-btn pkg-uninstall' : 'ops-refresh-btn pkg-install'}
                      aria-label={`${p.installed ? 'Uninstall' : 'Install'} ${p.item.name}`}
                      onClick={() => change([p.id], !p.installed, p.id)}>
                      {busy === p.id ? '…' : p.installed ? 'Uninstall' : 'Install'}
                    </button>
                  ) : (
                    <span className="pkg-badge">{p.installed ? 'Installed' : 'Not installed'}</span>
                  )}
                </div>
              </div>
            ))}
          </div>}
        </section>
      ))}
    </div>
  )
}
