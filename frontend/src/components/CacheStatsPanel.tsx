import { useEffect, useState } from 'react'
import { API_BASE } from '../types'

interface CacheStats {
  active_entries: number
  total_hits: number
}

export function CacheStatsPanel() {
  const [stats, setStats] = useState<CacheStats | null>(null)

  useEffect(() => {
    fetch(`${API_BASE}/api/cache`)
      .then((r) => r.json())
      .then((d) => setStats(d.stats))
      .catch(() => {})
  }, [])

  if (!stats) return <span className="field-hint">Loading cache stats…</span>

  return (
    <div className="cache-stats-grid">
      <div className="cache-stat-box">
        <span className="cache-stat-value">{stats.active_entries}</span>
        <span className="cache-stat-label">Active Entries</span>
      </div>
      <div className="cache-stat-box">
        <span className="cache-stat-value">{stats.total_hits}</span>
        <span className="cache-stat-label">Total Hits</span>
      </div>
    </div>
  )
}
