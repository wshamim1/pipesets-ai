import { useMemo, useState } from 'react'
import { useRunLogs, clearRunLogs, logsToText } from '../../utils/runLogs'
import type { RunLogLevel } from '../../utils/runLogs'
import { RunLogList } from '../RunLogList'

interface AppRecord {
  id: string
  name: string
}

interface Props {
  apps: AppRecord[]
}

const LEVELS: ('all' | RunLogLevel)[] = ['all', 'info', 'ok', 'tool', 'warn', 'error']

/** Global logs: every run of every pipeline, from the shared run-log store. */
export function GlobalLogsPanel({ apps }: Props) {
  const allLogs = useRunLogs()
  const [appFilter, setAppFilter] = useState('')
  const [levelFilter, setLevelFilter] = useState<'all' | RunLogLevel>('all')
  const [query, setQuery] = useState('')
  const [follow, setFollow] = useState(true)

  // Pipelines that have logs but are no longer in the apps list (e.g. deleted) still appear in the filter.
  const appOptions = useMemo(() => {
    const known = new Map(apps.map((a) => [a.id, a.name]))
    allLogs.forEach((l) => { if (!known.has(l.appId)) known.set(l.appId, l.appName || l.appId || '(no pipeline)') })
    return [...known.entries()].map(([id, name]) => ({ id, name }))
  }, [apps, allLogs])

  const q = query.trim().toLowerCase()
  const filtered = useMemo(
    () => allLogs.filter((l) =>
      (!appFilter || l.appId === appFilter) &&
      (levelFilter === 'all' || l.level === levelFilter) &&
      (!q || `${l.source} ${l.message} ${l.appName} ${l.runId}`.toLowerCase().includes(q))),
    [allLogs, appFilter, levelFilter, q],
  )

  const runCount = useMemo(() => new Set(filtered.map((l) => l.runId).filter(Boolean)).size, [filtered])
  const errorCount = useMemo(() => filtered.filter((l) => l.level === 'error').length, [filtered])

  return (
    <div className="ops-panel">
      <div className="ops-toolbar">
        <div className="ops-toolbar-left">
          <span className="ops-panel-title">All Logs</span>
          <span className="ops-count-badge">{filtered.length} line{filtered.length !== 1 ? 's' : ''}</span>
          <span className="ops-count-badge">{runCount} run{runCount !== 1 ? 's' : ''}</span>
          {errorCount > 0 && <span className="ops-count-badge" style={{ color: '#b91c1c' }}>{errorCount} error{errorCount > 1 ? 's' : ''}</span>}
        </div>
        <div className="ops-toolbar-right">
          <input
            type="text"
            className="ops-select"
            placeholder="Filter text, run id…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <select className="ops-select" value={appFilter} onChange={(e) => setAppFilter(e.target.value)}>
            <option value="">All Pipelines</option>
            {appOptions.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          <select className="ops-select" value={levelFilter} onChange={(e) => setLevelFilter(e.target.value as 'all' | RunLogLevel)}>
            {LEVELS.map((lv) => <option key={lv} value={lv}>{lv === 'all' ? 'All Levels' : lv.toUpperCase()}</option>)}
          </select>
          <label className="ops-follow">
            <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> Follow
          </label>
          <button
            type="button"
            className="ops-refresh-btn"
            disabled={filtered.length === 0}
            onClick={() => navigator.clipboard.writeText(logsToText(filtered))}
          >Copy</button>
          <button
            type="button"
            className="ops-refresh-btn"
            disabled={allLogs.length === 0}
            onClick={() => {
              const scope = appFilter ? `for "${appOptions.find((a) => a.id === appFilter)?.name ?? appFilter}"` : 'for ALL pipelines'
              if (window.confirm(`Clear logs ${scope}?`)) clearRunLogs(appFilter || undefined)
            }}
          >Clear</button>
        </div>
      </div>

      <RunLogList
        logs={filtered}
        showPipeline
        autoScroll={follow}
        className="run-log-list--global"
        emptyText="No logs yet. Run any pipeline from the Build tab and its activity will appear here."
      />
    </div>
  )
}
