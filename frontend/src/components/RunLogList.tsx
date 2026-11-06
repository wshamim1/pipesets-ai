import { useEffect, useMemo, useRef, useState } from 'react'
import { fmtLogTime, logsToText } from '../utils/runLogs'
import type { RunLogEntry } from '../utils/runLogs'

interface ListProps {
  logs: readonly RunLogEntry[]
  emptyText?: string
  /** Show the pipeline (app) name on each row — used by the global view. */
  showPipeline?: boolean
  autoScroll?: boolean
  className?: string
}

/** Dark terminal-style list of run log rows. */
export function RunLogList({ logs, emptyText = 'No logs yet.', showPipeline = false, autoScroll = false, className = '' }: ListProps) {
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (autoScroll) endRef.current?.scrollIntoView({ block: 'end' })
  }, [logs.length, autoScroll])

  return (
    <div className={`run-log-list ${className}`.trim()}>
      {logs.length === 0 && <span className="response-placeholder">{emptyText}</span>}
      {logs.map((l) => (
        <div key={l.id} className={`run-log-row run-log-${l.level}${showPipeline ? ' run-log-row--pipeline' : ''}`}>
          <span className="run-log-time">{fmtLogTime(l.ts)}</span>
          <span className="run-log-level">{l.level}</span>
          {showPipeline && <span className="run-log-pipeline" title={l.appId}>{l.appName || l.appId || '—'}</span>}
          <span className="run-log-source">{l.source}</span>
          <span className="run-log-msg">{l.message}</span>
        </div>
      ))}
      <div ref={endRef} />
    </div>
  )
}

interface TurnLogsProps {
  logs: readonly RunLogEntry[]
  runId?: string
}

/** Collapsible "Logs" strip shown right next to a run's result in the chat. Closed by default. */
export function TurnLogs({ logs, runId }: TurnLogsProps) {
  const [open, setOpen] = useState(false)
  const runLogs = useMemo(() => (runId ? logs.filter((l) => l.runId === runId) : []), [logs, runId])
  if (!runId || runLogs.length === 0) return null

  const errors = runLogs.filter((l) => l.level === 'error').length
  const warns = runLogs.filter((l) => l.level === 'warn').length

  return (
    <div className="turn-logs">
      <div className="turn-logs-header">
        <button type="button" className="turn-logs-toggle" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          <span className="turn-logs-chevron">{open ? '▼' : '▶'}</span>
          Logs
          <span className="turn-logs-count">{runLogs.length}</span>
          {errors > 0 && <span className="turn-logs-badge turn-logs-badge--error">{errors} error{errors > 1 ? 's' : ''}</span>}
          {warns > 0 && <span className="turn-logs-badge turn-logs-badge--warn">{warns} warn</span>}
        </button>
        {open && (
          <button
            type="button"
            className="copy-btn"
            onClick={() => navigator.clipboard.writeText(logsToText(runLogs))}
          >Copy</button>
        )}
      </div>
      {open && <RunLogList logs={runLogs} className="run-log-list--inline" />}
    </div>
  )
}
