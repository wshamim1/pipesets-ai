import { useState, useMemo } from 'react'
import { Activity, CheckCircle2, LayoutGrid, PencilLine } from 'lucide-react'
import type { AppRecord } from '../types'
import { API_BASE } from '../types'
import { ExportModal } from './ExportModal'
import { ImportCodeModal } from './ImportCodeModal'
import { blueprintToFlowData } from '../utils/blueprintToFlowData'
import { STARTER_BLUEPRINTS, buildBlueprintFlow } from '../blueprints'
import { fullRowsPageSize, useGridColumns } from '../hooks/useGridColumns'
import type { StarterBlueprint } from '../blueprints'
import { BlueprintPreviewModal } from './BlueprintPreviewModal'
import { useCredentials } from '../context/CredentialsContext'
import { PublishListingModal } from './marketplace/PublishListingModal'
import '../styles/marketplace.css'
import '../styles/apps-hub.css'

interface Props {
  apps: AppRecord[]
  currentApp: AppRecord | null
  onOpenApp: (app: AppRecord) => void
  onCreateApp: (name: string, description: string, flowData?: AppRecord['flow_data']) => Promise<any>
  onDeleteApp: (appId: string) => Promise<any>
  onRenameApp: (app: AppRecord) => void | Promise<void>
  onRefreshApps: () => void
}

// About this many blueprints per page, rounded up to whole rows of the grid (a 7-column screen shows 14)
const BLUEPRINTS_PER_PAGE_TARGET = 12
const BLUEPRINT_CARD_MIN_WIDTH = 320
const BLUEPRINT_GRID_GAP = 14
const BLUEPRINT_CATEGORIES = ['All', ...new Set(STARTER_BLUEPRINTS.map((b) => b.badge))]

export function AppsHubView({
  apps,
  currentApp,
  onOpenApp,
  onCreateApp,
  onDeleteApp,
  onRenameApp,
  onRefreshApps,
}: Props) {
  const [searchTerm, setSearchTerm] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'draft' | 'published'>('all')
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false)
  const [isImportOpen, setIsImportOpen] = useState(false)
  const { resolveApiKey } = useCredentials()
  const [exportingApp, setExportingApp] = useState<{ id: string; name: string } | null>(null)
  const [sharingApp, setSharingApp] = useState<AppRecord | null>(null)
  const [newAppName, setNewAppName] = useState('')
  const [newAppDesc, setNewAppDesc] = useState('')
  const [duplicatingId, setDuplicatingId] = useState<string | null>(null)
  const [blueprintSearch, setBlueprintSearch] = useState('')
  const [blueprintCategory, setBlueprintCategory] = useState('All')
  const [blueprintPage, setBlueprintPage] = useState(0)
  const [previewBlueprint, setPreviewBlueprint] = useState<StarterBlueprint | null>(null)
  // Until the user picks a tab, land on their apps — or on blueprints when they have none yet
  const [hubTabChoice, setHubTabChoice] = useState<'apps' | 'blueprints' | null>(null)
  const hubTab = hubTabChoice ?? (apps.length > 0 ? 'apps' : 'blueprints')

  const handleDuplicate = async (appId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    setDuplicatingId(appId)
    try {
      const res = await fetch(`${API_BASE}/api/apps/${appId}/duplicate`, { method: 'POST' })
      if (res.ok) {
        onRefreshApps()
      }
    } catch {
      // ignore
    } finally {
      setDuplicatingId(null)
    }
  }

  const handleDelete = async (appId: string, name: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (window.confirm(`Are you sure you want to delete "${name}"?`)) {
      await onDeleteApp(appId)
      onRefreshApps()
    }
  }

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newAppName.trim()) return
    const created = await onCreateApp(newAppName.trim(), newAppDesc.trim())
    setNewAppName('')
    setNewAppDesc('')
    setIsCreateModalOpen(false)
    if (created) onOpenApp(created)
  }

  const handleImportBlueprint = async (blueprint: any) => {
    const flow = blueprintToFlowData(blueprint)
    if (!flow) return
    setIsImportOpen(false)
    const created = await onCreateApp(blueprint?.label || 'Imported Pipeline', 'Imported from code', flow)
    if (created) onOpenApp(created)
  }

  const handleCreateFromTemplate = async (tpl: StarterBlueprint) => {
    const created = await onCreateApp(`${tpl.name}`, tpl.description, buildBlueprintFlow(tpl.id))
    if (created) {
      setPreviewBlueprint(null)
      onOpenApp(created)
    }
  }

  const filteredBlueprints = useMemo(() => {
    const q = blueprintSearch.trim().toLowerCase()
    return STARTER_BLUEPRINTS.filter((b) =>
      (blueprintCategory === 'All' || b.badge === blueprintCategory)
      && (!q || `${b.name} ${b.description} ${b.badge}`.toLowerCase().includes(q)),
    )
  }, [blueprintSearch, blueprintCategory])
  const { ref: blueprintGridRef, columns: blueprintColumns } = useGridColumns<HTMLDivElement>(BLUEPRINT_CARD_MIN_WIDTH, BLUEPRINT_GRID_GAP)
  const blueprintsPerPage = fullRowsPageSize(blueprintColumns, BLUEPRINTS_PER_PAGE_TARGET)
  const blueprintPageCount = Math.max(1, Math.ceil(filteredBlueprints.length / blueprintsPerPage))
  const currentBlueprintPage = Math.min(blueprintPage, blueprintPageCount - 1)
  const pagedBlueprints = filteredBlueprints.slice(
    currentBlueprintPage * blueprintsPerPage, (currentBlueprintPage + 1) * blueprintsPerPage,
  )

  const filteredApps = useMemo(() => {
    return apps.filter((a) => {
      const matchesSearch =
        a.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        a.description?.toLowerCase().includes(searchTerm.toLowerCase())
      const matchesStatus = statusFilter === 'all' || a.status === statusFilter
      return matchesSearch && matchesStatus
    })
  }, [apps, searchTerm, statusFilter])

  const publishedCount = apps.filter((a) => a.status === 'published').length
  const draftCount = apps.filter((a) => a.status === 'draft').length

  return (
    <div className="apps-hub" style={{ flex: 1, overflowY: 'auto', padding: '24px 32px' }}>
      {/* Top Banner */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>📱</span> Agent Applications Hub
          </h1>
          <p style={{ margin: '4px 0 0', color: '#64748b', fontSize: 13 }}>
            Manage, fork, and launch your autonomous agent workflows and RAG pipelines.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button
            type="button"
            onClick={onRefreshApps}
            style={{
              padding: '8px 14px',
              borderRadius: 6,
              border: '1px solid #cbd5e1',
              background: '#ffffff',
              fontSize: 13,
              cursor: 'pointer',
              fontWeight: 500,
              color: '#334155',
            }}
          >
            🔄 Refresh
          </button>
          <button
            type="button"
            onClick={() => setIsImportOpen(true)}
            style={{
              padding: '8px 14px',
              borderRadius: 6,
              border: '1px solid #cbd5e1',
              background: '#ffffff',
              fontSize: 13,
              cursor: 'pointer',
              fontWeight: 500,
              color: '#334155',
            }}
          >
            ↩ Import Code
          </button>
          <button
            type="button"
            onClick={() => setIsCreateModalOpen(true)}
            style={{
              padding: '8px 18px',
              borderRadius: 6,
              background: '#2563eb',
              color: '#ffffff',
              border: 'none',
              fontSize: 13,
              fontWeight: 600,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              boxShadow: '0 2px 4px rgba(37,99,235,0.2)',
            }}
          >
            <span>+</span> New Application
          </button>
        </div>
      </div>

      {/* Metrics Row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14, marginBottom: 24 }}>
        {([
          { label: 'Total Applications', value: apps.length, accent: '#475569', Icon: LayoutGrid },
          { label: 'Published Workflows', value: publishedCount, accent: '#16a34a', Icon: CheckCircle2 },
          { label: 'Draft Builds', value: draftCount, accent: '#d97706', Icon: PencilLine },
          { label: 'Currently Active in Builder', value: currentApp ? currentApp.name : 'None', accent: '#4f46e5', Icon: Activity },
        ] as const).map(({ label, value, accent, Icon }) => (
          <div key={label} className="apps-hub-metric" style={{ '--metric-accent': accent } as React.CSSProperties}>
            <div style={{ minWidth: 0 }}>
              <div className="apps-hub-metric-label">{label}</div>
              <div className={`apps-hub-metric-value${typeof value === 'string' ? ' apps-hub-metric-value--text' : ''}`}>{value}</div>
            </div>
            <span className="apps-hub-metric-icon"><Icon size={18} strokeWidth={2} /></span>
          </div>
        ))}
      </div>

      {/* Hub Tabs */}
      <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid var(--surface-border)', marginBottom: 18 }}>
        {([
          { id: 'apps', label: '📁 My Applications', count: apps.length },
          { id: 'blueprints', label: '⚡ Starter Blueprints', count: STARTER_BLUEPRINTS.length },
        ] as const).map((tab) => {
          const active = hubTab === tab.id
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => setHubTabChoice(tab.id)}
              style={{
                padding: '8px 14px',
                marginBottom: -1,
                border: 'none',
                borderBottom: `2px solid ${active ? '#2563eb' : 'transparent'}`,
                background: 'transparent',
                fontSize: 13,
                fontWeight: active ? 600 : 500,
                color: active ? '#1e293b' : '#64748b',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              {tab.label}
              <span style={{
                fontSize: 11,
                padding: '1px 7px',
                borderRadius: 10,
                background: active ? '#eff6ff' : '#f1f5f9',
                color: active ? '#2563eb' : '#64748b',
                fontWeight: 600,
              }}>
                {tab.count}
              </span>
            </button>
          )
        })}
      </div>

      {/* Starter Templates Section */}
      {hubTab === 'blueprints' && (
      <div style={{ marginBottom: 28 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, marginBottom: 10 }}>
          <p style={{ margin: 0, fontSize: 13, color: '#64748b' }}>
            Clone a ready-made pipeline, then customise it in the canvas.
          </p>
          <input
            type="text"
            placeholder="Search blueprints..."
            value={blueprintSearch}
            onChange={(e) => { setBlueprintSearch(e.target.value); setBlueprintPage(0) }}
            style={{
              padding: '6px 12px',
              fontSize: 13,
              border: '1px solid #cbd5e1',
              borderRadius: 6,
              width: 240,
              background: '#ffffff',
            }}
          />
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
          {BLUEPRINT_CATEGORIES.map((cat) => {
            const active = blueprintCategory === cat
            return (
              <button
                key={cat}
                type="button"
                onClick={() => { setBlueprintCategory(cat); setBlueprintPage(0) }}
                style={{
                  padding: '3px 10px',
                  fontSize: 12,
                  borderRadius: 12,
                  border: `1px solid ${active ? '#2563eb' : '#e2e8f0'}`,
                  background: active ? '#eff6ff' : '#ffffff',
                  color: active ? '#2563eb' : '#64748b',
                  fontWeight: active ? 600 : 400,
                  cursor: 'pointer',
                }}
              >
                {cat}
              </button>
            )
          })}
        </div>
        {pagedBlueprints.length === 0 && (
          <div style={{ padding: '24px 0', textAlign: 'center', fontSize: 13, color: '#64748b' }}>
            No blueprints match “{blueprintSearch}”{blueprintCategory !== 'All' ? ` in ${blueprintCategory}` : ''}.
          </div>
        )}
        <div ref={blueprintGridRef}
          style={{ display: 'grid', gridTemplateColumns: `repeat(auto-fill, minmax(${BLUEPRINT_CARD_MIN_WIDTH}px, 1fr))`, gap: BLUEPRINT_GRID_GAP }}>
          {pagedBlueprints.map((tpl) => (
            <div
              key={tpl.id}
              className="apps-hub-card"
              style={{
                padding: '16px',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
              }}
            >
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 24 }}>{tpl.icon}</span>
                  <span style={{ fontSize: 10, background: '#eff6ff', color: '#2563eb', padding: '2px 8px', borderRadius: 12, fontWeight: 600 }}>
                    {tpl.badge}
                  </span>
                </div>
                <h4 style={{ margin: '10px 0 4px', fontSize: 14, fontWeight: 600, color: '#1e293b' }}>{tpl.name}</h4>
                <p style={{ margin: 0, fontSize: 12, color: '#64748b', lineHeight: 1.4 }}>{tpl.description}</p>
              </div>
              <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
                <button
                  type="button"
                  onClick={() => setPreviewBlueprint(tpl)}
                  style={{
                    flex: 1,
                    padding: '6px 12px',
                    borderRadius: 6,
                    border: '1px solid #e2e8f0',
                    background: '#ffffff',
                    fontSize: 12,
                    fontWeight: 600,
                    color: '#334155',
                    cursor: 'pointer',
                    textAlign: 'center',
                  }}
                >
                  👁 Preview
                </button>
                <button
                  type="button"
                  onClick={() => handleCreateFromTemplate(tpl)}
                  style={{
                    flex: 1,
                    padding: '6px 12px',
                    borderRadius: 6,
                    border: '1px solid #e2e8f0',
                    background: '#f8fafc',
                    fontSize: 12,
                    fontWeight: 600,
                    color: '#2563eb',
                    cursor: 'pointer',
                    textAlign: 'center',
                  }}
                >
                  + Clone
                </button>
              </div>
            </div>
          ))}
        </div>
        {filteredBlueprints.length > blueprintsPerPage && (
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 12, fontSize: 12, color: '#64748b' }}>
            <span>
              Showing {currentBlueprintPage * blueprintsPerPage + 1}–{currentBlueprintPage * blueprintsPerPage + pagedBlueprints.length} of {filteredBlueprints.length} blueprints
            </span>
            <div style={{ display: 'flex', gap: 4 }}>
              {[
                { label: '‹ Prev', page: currentBlueprintPage - 1 },
                ...Array.from({ length: blueprintPageCount }, (_, i) => ({ label: String(i + 1), page: i })),
                { label: 'Next ›', page: currentBlueprintPage + 1 },
              ].map(({ label, page }) => {
                const active = page === currentBlueprintPage && /^\d+$/.test(label)
                const disabled = page < 0 || page >= blueprintPageCount
                return (
                  <button
                    key={label}
                    type="button"
                    disabled={disabled}
                    onClick={() => setBlueprintPage(page)}
                    style={{
                      minWidth: 28,
                      padding: '3px 8px',
                      fontSize: 12,
                      borderRadius: 6,
                      border: '1px solid #e2e8f0',
                      background: active ? '#2563eb' : '#ffffff',
                      color: active ? '#ffffff' : disabled ? '#cbd5e1' : '#334155',
                      fontWeight: active ? 600 : 400,
                      cursor: disabled ? 'default' : 'pointer',
                    }}
                  >
                    {label}
                  </button>
                )
              })}
            </div>
          </div>
        )}
      </div>
      )}

      {hubTab === 'apps' && (<>
      {/* Apps Search & List Filter */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <input
            type="text"
            placeholder="Search apps by name or description..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={{
              padding: '6px 12px',
              fontSize: 13,
              border: '1px solid #cbd5e1',
              borderRadius: 6,
              width: 280,
              background: '#ffffff',
            }}
          />
          <div style={{ display: 'inline-flex', background: '#dfe6ef', borderRadius: 6, padding: 2 }}>
            {(['all', 'published', 'draft'] as const).map((filter) => (
              <button
                key={filter}
                type="button"
                onClick={() => setStatusFilter(filter)}
                style={{
                  padding: '4px 10px',
                  fontSize: 12,
                  borderRadius: 4,
                  border: 'none',
                  cursor: 'pointer',
                  background: statusFilter === filter ? '#ffffff' : 'transparent',
                  fontWeight: statusFilter === filter ? 600 : 400,
                  color: statusFilter === filter ? '#1e293b' : '#64748b',
                  boxShadow: statusFilter === filter ? '0 1px 2px rgba(0,0,0,0.05)' : 'none',
                  textTransform: 'capitalize',
                }}
              >
                {filter}
              </button>
            ))}
          </div>
        </div>
        <span style={{ fontSize: 12, color: '#64748b' }}>
          Showing <strong>{filteredApps.length}</strong> of {apps.length} applications
        </span>
      </div>

      {/* Applications Grid */}
      {filteredApps.length === 0 ? (
        <div className="apps-hub-card" style={{ padding: '40px 20px', textAlign: 'center' }}>
          <span style={{ fontSize: 32 }}>📁</span>
          <p style={{ margin: '8px 0 0', fontWeight: 600, color: '#334155' }}>No applications found</p>
          <p style={{ margin: '4px 0 14px', fontSize: 12, color: '#64748b' }}>
            {searchTerm ? 'Try a different search query or clear your filter.' : 'Create your first app to get started!'}
          </p>
          <button
            type="button"
            onClick={() => setIsCreateModalOpen(true)}
            style={{
              padding: '6px 14px',
              borderRadius: 6,
              background: '#2563eb',
              color: '#fff',
              border: 'none',
              fontSize: 12,
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            + Create New App
          </button>
          {!searchTerm && (
            <button
              type="button"
              onClick={() => setHubTabChoice('blueprints')}
              style={{
                marginLeft: 8,
                padding: '6px 14px',
                borderRadius: 6,
                background: '#ffffff',
                color: '#2563eb',
                border: '1px solid #e2e8f0',
                fontSize: 12,
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              ⚡ Start from a blueprint
            </button>
          )}
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 16 }}>
          {filteredApps.map((app) => {
            const isSelected = currentApp?.id === app.id
            const nodeCount = app.flow_data?.nodes?.length || 0
            const edgeCount = app.flow_data?.edges?.length || 0

            return (
              <div
                key={app.id}
                onClick={() => onOpenApp(app)}
                className={`apps-hub-card${isSelected ? ' apps-hub-card--selected' : ''}`}
                style={{
                  padding: 16,
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'space-between',
                  cursor: 'pointer',
                  position: 'relative',
                }}
              >
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div style={{ flex: 1, marginRight: 8 }}>
                      <h4 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: '#0f172a', display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span>⚡</span> {app.name}
                      </h4>
                      <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>ID: {app.id}</div>
                    </div>
                    <span
                      style={{
                        fontSize: 11,
                        padding: '2px 8px',
                        borderRadius: 12,
                        fontWeight: 600,
                        background: app.status === 'published' ? '#dcfce7' : '#fef3c7',
                        color: app.status === 'published' ? '#15803d' : '#b45309',
                        border: `1px solid ${app.status === 'published' ? '#bbf7d0' : '#fde68a'}`,
                      }}
                    >
                      {app.status === 'published' ? `v${app.version} Published` : 'Draft'}
                    </span>
                  </div>

                  <p style={{ margin: '10px 0 12px', fontSize: 12, color: '#475569', lineHeight: 1.4, minHeight: 34 }}>
                    {app.description || <span style={{ color: '#94a3b8', fontStyle: 'italic' }}>No description provided</span>}
                  </p>

                  <div style={{ display: 'flex', gap: 12, fontSize: 11, color: '#64748b', background: 'var(--surface-subtle)', padding: '6px 10px', borderRadius: 6 }}>
                    <span>🔲 <strong>{nodeCount}</strong> Nodes</span>
                    <span>🔗 <strong>{edgeCount}</strong> Edges</span>
                    <span style={{ marginLeft: 'auto' }}>
                      🕒 {new Date(app.updated_at).toLocaleDateString([], { month: 'short', day: 'numeric' })}
                    </span>
                  </div>
                </div>

                <div style={{ marginTop: 14, paddingTop: 10, borderTop: '1px solid #e6ebf2', display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      onOpenApp(app)
                    }}
                    style={{
                      padding: '4px 10px',
                      borderRadius: 4,
                      background: isSelected ? '#2563eb' : '#eff6ff',
                      color: isSelected ? '#ffffff' : '#1d4ed8',
                      border: 'none',
                      fontSize: 11,
                      fontWeight: 600,
                      cursor: 'pointer',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {isSelected ? '✓ Open in Canvas' : 'Open in Canvas ➔'}
                  </button>

                  <div className="apps-hub-card-actions" style={{ display: 'flex', gap: 6 }}>
                    <button
                      type="button"
                      title="Export Pipeline (JSON / LangChain / Native Python)"
                      onClick={(e) => {
                        e.stopPropagation()
                        setExportingApp({ id: app.id, name: app.name })
                      }}
                      style={{
                        padding: '4px 8px',
                        borderRadius: 4,
                        border: '1px solid #cbd5e1',
                        background: '#ffffff',
                        fontSize: 11,
                        cursor: 'pointer',
                        color: '#334155',
                        fontWeight: 500,
                      }}
                    >
                      ↑ Export
                    </button>
                    {app.status === 'published' && (
                      <button
                        type="button"
                        title="Share this published version to the marketplace"
                        onClick={(e) => {
                          e.stopPropagation()
                          setSharingApp(app)
                        }}
                        style={{
                          padding: '4px 8px',
                          borderRadius: 4,
                          border: '1px solid #c7d2fe',
                          background: '#eef2ff',
                          fontSize: 11,
                          cursor: 'pointer',
                          color: '#4338ca',
                          fontWeight: 600,
                        }}
                      >
                        🛒 Share
                      </button>
                    )}
                    <button
                      type="button"
                      title="Rename Application"
                      onClick={(e) => {
                        e.stopPropagation()
                        void onRenameApp(app)
                      }}
                      style={{
                        padding: '4px 8px',
                        borderRadius: 4,
                        border: '1px solid #e2e8f0',
                        background: '#ffffff',
                        fontSize: 11,
                        cursor: 'pointer',
                        color: '#475569',
                      }}
                    >
                      ✏️ Rename
                    </button>
                    <button
                      type="button"
                      title="Duplicate / Fork Application"
                      disabled={duplicatingId === app.id}
                      onClick={(e) => handleDuplicate(app.id, e)}
                      style={{
                        padding: '4px 8px',
                        borderRadius: 4,
                        border: '1px solid #e2e8f0',
                        background: '#ffffff',
                        fontSize: 11,
                        cursor: 'pointer',
                        color: '#475569',
                      }}
                    >
                      {duplicatingId === app.id ? '…' : '📋 Fork'}
                    </button>
                    <button
                      type="button"
                      title="Delete Application"
                      onClick={(e) => handleDelete(app.id, app.name, e)}
                      style={{
                        padding: '4px 8px',
                        borderRadius: 4,
                        border: '1px solid #fee2e2',
                        background: '#fef2f2',
                        fontSize: 11,
                        cursor: 'pointer',
                        color: '#b91c1c',
                      }}
                    >
                      🗑️
                    </button>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
      </>)}

      {previewBlueprint && (
        <BlueprintPreviewModal
          blueprint={previewBlueprint}
          onClose={() => setPreviewBlueprint(null)}
          onClone={handleCreateFromTemplate}
        />
      )}

      {/* New App Modal */}
      {isCreateModalOpen && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(15,23,42,0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
          onClick={() => setIsCreateModalOpen(false)}
        >
          <div
            style={{
              background: '#ffffff',
              borderRadius: 12,
              padding: 24,
              width: 440,
              maxWidth: '90vw',
              boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1), 0 10px 10px -5px rgba(0,0,0,0.04)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ margin: '0 0 14px', fontSize: 16, fontWeight: 700, color: '#0f172a' }}>
              Create New Agent Application
            </h3>
            <form onSubmit={handleCreateSubmit}>
              <div style={{ marginBottom: 12 }}>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#334155', marginBottom: 4 }}>
                  Application Name *
                </label>
                <input
                  type="text"
                  placeholder="e.g. Customer Support Agent"
                  value={newAppName}
                  onChange={(e) => setNewAppName(e.target.value)}
                  required
                  autoFocus
                  style={{
                    width: '100%',
                    padding: '8px 10px',
                    fontSize: 13,
                    border: '1px solid #cbd5e1',
                    borderRadius: 6,
                    boxSizing: 'border-box',
                  }}
                />
              </div>
              <div style={{ marginBottom: 18 }}>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#334155', marginBottom: 4 }}>
                  Description
                </label>
                <textarea
                  rows={3}
                  placeholder="What is this application intended to do?"
                  value={newAppDesc}
                  onChange={(e) => setNewAppDesc(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 10px',
                    fontSize: 13,
                    border: '1px solid #cbd5e1',
                    borderRadius: 6,
                    boxSizing: 'border-box',
                    resize: 'vertical',
                  }}
                />
              </div>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
                <button
                  type="button"
                  onClick={() => setIsCreateModalOpen(false)}
                  style={{
                    padding: '6px 14px',
                    borderRadius: 6,
                    border: '1px solid #cbd5e1',
                    background: '#ffffff',
                    fontSize: 13,
                    cursor: 'pointer',
                  }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  style={{
                    padding: '6px 16px',
                    borderRadius: 6,
                    background: '#2563eb',
                    color: '#ffffff',
                    border: 'none',
                    fontSize: 13,
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  Create Application
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Export Modal */}
      {isImportOpen && (
        <ImportCodeModal
          onClose={() => setIsImportOpen(false)}
          llmConfig={{ provider: 'openai', model: 'gpt-4o', api_key: resolveApiKey('openai', ''), base_url: '' }}
          onImport={(blueprint) => { void handleImportBlueprint(blueprint) }}
        />
      )}

      {sharingApp && (
        <PublishListingModal app={sharingApp} onClose={() => setSharingApp(null)} onPublished={() => {}} />
      )}
      {exportingApp && (
        <ExportModal
          appId={exportingApp.id}
          appName={exportingApp.name}
          onClose={() => setExportingApp(null)}
        />
      )}
    </div>
  )
}
