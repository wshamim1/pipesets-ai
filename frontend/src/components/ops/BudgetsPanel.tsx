import { useState, useEffect, useCallback } from 'react'
import { API_BASE } from '../../types'

interface AppRecord {
  id: string
  name: string
}

interface Budget {
  id: string
  scope: 'global' | 'app'
  scope_id: string
  period: 'daily' | 'monthly' | 'total'
  limit_usd: number
  action: 'block' | 'warn'
  spent_usd: number
  pct_used: number
  exceeded: boolean
}

interface Props {
  apps: AppRecord[]
  onChanged?: () => void
}

export function BudgetsPanel({ apps, onChanged }: Props) {
  const [budgets, setBudgets] = useState<Budget[]>([])
  const [error, setError] = useState<string | null>(null)
  const [scope, setScope] = useState<'global' | 'app'>('global')
  const [scopeId, setScopeId] = useState('')
  const [period, setPeriod] = useState<'daily' | 'monthly' | 'total'>('monthly')
  const [limit, setLimit] = useState('')
  const [action, setAction] = useState<'block' | 'warn'>('block')
  const [saving, setSaving] = useState(false)

  const appName = (id: string) => apps.find((a) => a.id === id)?.name ?? id

  const load = useCallback(() => {
    fetch(`${API_BASE}/api/budgets`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.statusText))))
      .then((d: Budget[]) => { setBudgets(d); setError(null) })
      .catch((e) => setError(`Failed to load budgets: ${e.message}`))
  }, [])

  useEffect(() => { load() }, [load])

  const save = async () => {
    const limitUsd = parseFloat(limit)
    if (!(limitUsd > 0)) { setError('Limit must be greater than 0.'); return }
    if (scope === 'app' && !scopeId) { setError('Select a pipeline for an app-scoped budget.'); return }
    setSaving(true)
    try {
      const res = await fetch(`${API_BASE}/api/budgets`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scope, scope_id: scope === 'app' ? scopeId : '', period, limit_usd: limitUsd, action }),
      })
      if (!res.ok) throw new Error(await res.text().catch(() => res.statusText))
      setLimit('')
      setError(null)
      load()
      onChanged?.()
    } catch (e) {
      setError(`Save failed: ${(e as Error).message}`)
    } finally {
      setSaving(false)
    }
  }

  const remove = async (id: string) => {
    const res = await fetch(`${API_BASE}/api/budgets/${encodeURIComponent(id)}`, { method: 'DELETE' })
    if (!res.ok) { setError(`Delete failed: ${res.statusText}`); return }
    load()
    onChanged?.()
  }

  return (
    <div className="cost-card">
      <div className="cost-card-title">Spend Budgets</div>

      {error && <div style={{ color: '#dc2626', fontSize: 12, marginBottom: 10 }}>{error}</div>}

      {budgets.length === 0 ? (
        <div style={{ fontSize: 12, color: '#64748b', marginBottom: 12 }}>
          No budgets set. Runs are not capped (Ollama, llama.cpp and mock runs are never counted).
        </div>
      ) : (
        <div className="cost-model-list" style={{ marginBottom: 14 }}>
          {budgets.map((b) => {
            const pct = Math.min(100, b.pct_used)
            const color = b.exceeded ? '#dc2626' : b.pct_used >= 80 ? '#f59e0b' : '#16a34a'
            return (
              <div key={b.id} className="cost-model-row">
                <div className="cost-model-meta">
                  <span className="cost-model-name">
                    {b.scope === 'global' ? 'Global' : appName(b.scope_id)} · {b.period}
                  </span>
                  <span className="cost-model-traces">{b.action === 'block' ? 'blocks runs' : 'warns only'}</span>
                  {b.exceeded && <span className="cost-model-errors">⚠ exceeded</span>}
                  <button
                    type="button"
                    className="ops-refresh-btn"
                    style={{ marginLeft: 'auto', height: 24, padding: '0 8px' }}
                    onClick={() => remove(b.id)}
                  >
                    Delete
                  </button>
                </div>
                <div className="cost-model-bar-row">
                  <div className="cost-model-track">
                    <div className="cost-model-bar" style={{ width: `${Math.max(2, pct)}%`, background: color }} />
                  </div>
                  <span className="cost-model-cost">
                    ${b.spent_usd.toFixed(4)} / ${b.limit_usd.toFixed(2)} ({b.pct_used}%)
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <select className="ops-select" value={scope} onChange={(e) => setScope(e.target.value as 'global' | 'app')}>
          <option value="global">Global</option>
          <option value="app">Pipeline</option>
        </select>
        {scope === 'app' && (
          <select className="ops-select" value={scopeId} onChange={(e) => setScopeId(e.target.value)}>
            <option value="">Select pipeline…</option>
            {apps.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        )}
        <select className="ops-select" value={period} onChange={(e) => setPeriod(e.target.value as 'daily' | 'monthly' | 'total')}>
          <option value="daily">Daily</option>
          <option value="monthly">Monthly</option>
          <option value="total">Total</option>
        </select>
        <input
          type="number" min="0" step="0.01" placeholder="Limit (USD)"
          className="ops-select" style={{ width: 110, cursor: 'text' }}
          value={limit} onChange={(e) => setLimit(e.target.value)}
        />
        <select className="ops-select" value={action} onChange={(e) => setAction(e.target.value as 'block' | 'warn')}>
          <option value="block">Block runs</option>
          <option value="warn">Warn only</option>
        </select>
        <button type="button" className="ops-refresh-btn" onClick={save} disabled={saving}>
          {saving ? '…' : 'Set budget'}
        </button>
      </div>
    </div>
  )
}
