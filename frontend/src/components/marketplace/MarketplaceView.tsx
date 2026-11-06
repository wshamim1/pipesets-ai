import { useCallback, useEffect, useState } from 'react'
import { API_BASE } from '../../types'
import { useCredentials } from '../../context/CredentialsContext'
import { CATEGORY_LABELS, errorDetail, type Listing } from './types'
import { ListingDetailDrawer } from './ListingDetailDrawer'
import '../../styles/marketplace.css'

type Tab = 'browse' | 'mine' | 'imported'

type ImportRecord = {
  listing_id: string
  listing_name: string | null
  version: number
  latest_version: number | null
  app_id: string
  app_name: string | null
  created_at: string
  app_exists: boolean
  listing_exists: boolean
  update_available: boolean
}

interface Props {
  /** Open an imported app in the canvas */
  onOpenApp: (appId: string) => void
  /** Imports create apps; let the parent reload its app list */
  onAppsChanged: () => void
}

export function MarketplaceView({ onOpenApp, onAppsChanged }: Props) {
  const { resolveApiKey } = useCredentials()
  const [tab, setTab] = useState<Tab>('browse')
  const [q, setQ] = useState('')
  const [category, setCategory] = useState('')
  const [sort, setSort] = useState('popular')
  const [listings, setListings] = useState<Listing[]>([])
  const [imports, setImports] = useState<ImportRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [openId, setOpenId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      if (tab === 'imported') {
        const res = await fetch(`${API_BASE}/api/marketplace/imports`)
        if (!res.ok) throw new Error(await errorDetail(res, 'Failed to load imports'))
        setImports((await res.json()).imports)
      } else {
        const params = new URLSearchParams({ q, category, sort, mine: tab === 'mine' ? 'true' : 'false' })
        const res = await fetch(`${API_BASE}/api/marketplace/listings?${params}`)
        if (!res.ok) throw new Error(await errorDetail(res, 'Failed to load the marketplace'))
        setListings((await res.json()).listings)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load the marketplace')
    } finally {
      setLoading(false)
    }
  }, [tab, q, category, sort])

  useEffect(() => {
    const t = setTimeout(load, q ? 250 : 0) // debounce typing in the search box
    return () => clearTimeout(t)
  }, [load, q])

  return (
    <div className="mkt-root">
      <div className="mkt-header">
        <div>
          <h1 className="mkt-title">Marketplace</h1>
          <p className="mkt-muted">Pipelines shared by other teams. Try them with your own keys, then import a copy into your project.</p>
        </div>
        <div className="mkt-tabs" role="tablist">
          {(['browse', 'mine', 'imported'] as Tab[]).map((t) => (
            <button key={t} type="button" role="tab" aria-selected={tab === t}
              className={`mkt-tab${tab === t ? ' mkt-tab--active' : ''}`} onClick={() => setTab(t)}>
              {t === 'browse' ? 'Browse' : t === 'mine' ? 'My listings' : 'Imported'}
            </button>
          ))}
        </div>
      </div>

      {tab !== 'imported' && (
        <div className="mkt-filters">
          <input className="mkt-search" type="search" placeholder="Search name, summary or tag" value={q} onChange={(e) => setQ(e.target.value)} />
          <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Category">
            <option value="">All categories</option>
            {Object.entries(CATEGORY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort">
            <option value="popular">Most imported</option>
            <option value="recent">Recently updated</option>
            <option value="name">Name</option>
          </select>
        </div>
      )}

      {error && <div className="mkt-note mkt-note--error">{error}</div>}

      {tab === 'imported' ? (
        <div className="mkt-imports">
          {!loading && imports.length === 0 && <p className="mkt-empty">Nothing imported into this project yet.</p>}
          {imports.map((imp) => (
            <div key={imp.app_id + imp.created_at} className="mkt-import-row">
              <div>
                <strong>{imp.app_name ?? '(app deleted)'}</strong>
                <small>from {imp.listing_name ?? 'a removed listing'} v{imp.version} · {new Date(imp.created_at).toLocaleDateString()}</small>
              </div>
              <div className="mkt-row-actions">
                {imp.update_available && imp.listing_exists && (
                  <button type="button" className="mkt-pill mkt-pill--update" onClick={() => setOpenId(imp.listing_id)}>
                    v{imp.latest_version} available
                  </button>
                )}
                {imp.app_exists && <button type="button" className="mkt-btn" onClick={() => onOpenApp(imp.app_id)}>Open</button>}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="mkt-grid">
          {!loading && listings.length === 0 && (
            <p className="mkt-empty">
              {tab === 'mine'
                ? 'You haven’t listed anything. In Apps Hub, publish an app, then use “Share to marketplace”.'
                : 'No pipelines match. Try another search or category.'}
            </p>
          )}
          {listings.map((l) => (
            <button key={l.id} type="button" className="mkt-card" onClick={() => setOpenId(l.id)}>
              <div className="mkt-card-top">
                <span className="mkt-chip">{CATEGORY_LABELS[l.category] ?? l.category}</span>
                {l.visibility === 'tenant' && <span className="mkt-chip mkt-chip--private">Tenant only</span>}
                {l.status === 'unlisted' && <span className="mkt-chip mkt-chip--muted">Unlisted</span>}
              </div>
              <div className="mkt-card-name">{l.name}</div>
              <div className="mkt-card-summary">{l.summary || l.description || 'No description'}</div>
              <div className="mkt-card-meta">
                <span>{l.node_count} nodes{l.uses_agents ? ' · agents' : ''}{l.uses_rag ? ' · RAG' : ''}</span>
                <span>v{l.latest_version}</span>
              </div>
              <div className="mkt-card-foot">
                <span title={l.publisher.tenant_name}>by {l.publisher.user_name || l.publisher.tenant_name}</span>
                <span>⬇ {l.import_count} · ▶ {l.try_count}</span>
              </div>
            </button>
          ))}
        </div>
      )}

      {openId && (
        <ListingDetailDrawer
          listingId={openId}
          resolveApiKey={resolveApiKey}
          onClose={() => setOpenId(null)}
          onChanged={load}
          onImported={(appId) => {
            onAppsChanged()
            load()
            if (window.confirm('Imported as a draft app in your current project. Open it in the canvas now?')) onOpenApp(appId)
          }}
        />
      )}
    </div>
  )
}
