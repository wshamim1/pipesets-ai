import { useCallback, useEffect, useState } from 'react'
import { API_BASE } from '../../types'

export interface Job {
  id: string
  kind: string
  label: string
  status: Status
  attempts: number
  max_attempts: number
  last_error: string | null
  created_at: string
  updated_at: string
  finished_at: string | null
  source: { type: string; id: string } | null
}

type Status = 'queued' | 'running' | 'done' | 'dead'
type Counts = Record<Status, number>

// Failed first: the reason to open this page
const STATUSES: { id: Status; label: string; when: string }[] = [
  { id: 'dead', label: 'Failed', when: 'Failed' },
  { id: 'queued', label: 'Queued', when: 'Updated' },
  { id: 'running', label: 'Running', when: 'Started' },
  { id: 'done', label: 'Done', when: 'Finished' },
]

// Job timestamps are UTC with a Z
const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : '—')

async function errorText(res: Response): Promise<string> {
  if (res.status === 403) return 'You need write access to apps in this project to retry or discard jobs.'
  const body = await res.json().catch(() => ({}))
  return typeof body.detail === 'string' ? body.detail : `HTTP ${res.status}`
}

/** Automation → Jobs: background work — scheduled / webhook runs, notifications — by status;
 *  failed ones (dead letters) can be retried or discarded. */
export function JobsPanel() {
  const [status, setStatus] = useState<Status>('dead')
  const [jobs, setJobs] = useState<Job[]>([])
  const [counts, setCounts] = useState<Counts | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(async (s: Status) => {
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${API_BASE}/api/jobs?status=${s}`)
      if (!res.ok) {
        setError(await errorText(res))
        return
      }
      const body: { jobs: Job[]; counts: Counts } = await res.json()
      setJobs(body.jobs)
      setCounts(body.counts)
    } catch {
      setError('Backend not reachable.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load(status) }, [status, load])

  const act = async (job: Job, action: 'retry' | 'discard' | 'cancel') => {
    if (action === 'discard' && !window.confirm(`Discard “${job.label}”? It won't run again.`)) return
    if (action === 'cancel' && !window.confirm(`Cancel “${job.label}”? It stops wherever it runs and is recorded as cancelled.`)) return
    setBusy(job.id)
    setError('')
    try {
      const res = action === 'discard'
        ? await fetch(`${API_BASE}/api/jobs/${job.id}`, { method: 'DELETE' })
        : await fetch(`${API_BASE}/api/jobs/${job.id}/${action}`, { method: 'POST' })
      if (res.ok) await load(status)
      else setError(await errorText(res))
    } catch {
      setError('Backend not reachable.')
    } finally {
      setBusy(null)
    }
  }

  const current = STATUSES.find((s) => s.id === status)!
  const failed = status === 'dead'
  const cancellable = status === 'queued' || status === 'running'

  return (
    <div className="ops-panel">
      <div className="ops-toolbar">
        <div className="ops-toolbar-left">
          <span className="ops-panel-title">Jobs</span>
          <select className="ops-select" aria-label="Status" value={status}
            onChange={(e) => setStatus(e.target.value as Status)}>
            {STATUSES.map((s) => (
              <option key={s.id} value={s.id}>{s.label}{counts ? ` (${counts[s.id]})` : ''}</option>
            ))}
          </select>
        </div>
        <div className="ops-toolbar-right">
          <button type="button" className="ops-refresh-btn" onClick={() => load(status)} disabled={loading}>
            {loading ? 'Loading…' : '↻ Refresh'}
          </button>
        </div>
      </div>

      <div className="apikeys-body">
        <div className="apikeys-intro">
          Scheduled runs, webhook runs and notifications run in the background and are retried with backoff.
          The ones that failed every attempt are listed under <strong>Failed</strong>: <strong>Retry</strong> queues
          one again with a fresh set of attempts, <strong>Discard</strong> drops it. A queued or running job can be
          {' '}<strong>cancelled</strong>, wherever it runs. Failed jobs are kept for 30 days
          and finished ones for 7 by default (<code>JOB_KEEP_DEAD_DAYS</code>, <code>JOB_KEEP_DONE_DAYS</code>).
        </div>

        {error && <div className="apikeys-error" role="alert">{error}</div>}

        <div className="apikeys-table">
          {jobs.length > 0 && (
            <div className="ops-table-header">
              <span className="jobs-col-label">Job</span>
              <span className="jobs-col-error">Last error</span>
              <span className="jobs-col-attempts">Attempts</span>
              <span className="apikeys-col-date">{current.when}</span>
              {(failed || cancellable) && <span className="jobs-col-actions" />}
            </div>
          )}
          <div className="ops-list">
            {jobs.length === 0 && !loading && !error && (
              <div className="ops-empty">No {current.label.toLowerCase()} jobs.</div>
            )}
            {jobs.map((j) => (
              <div key={j.id} className="ops-pipeline-row" title={`${j.kind} · ${j.id}`}>
                <span className="jobs-col-label">{j.label}</span>
                <span className="jobs-col-error">{j.last_error || '—'}</span>
                <span className="jobs-col-attempts">{j.attempts}{j.max_attempts ? ` / ${j.max_attempts}` : ''}</span>
                <span className="apikeys-col-date">{fmt(j.finished_at ?? j.updated_at)}</span>
                {failed && (
                  <span className="jobs-col-actions">
                    <button type="button" className="ops-refresh-btn" disabled={busy === j.id} onClick={() => act(j, 'retry')}>
                      Retry
                    </button>
                    <button type="button" className="ops-link-btn" disabled={busy === j.id} onClick={() => act(j, 'discard')}>
                      Discard
                    </button>
                  </span>
                )}
                {cancellable && (
                  <span className="jobs-col-actions">
                    <button type="button" className="ops-link-btn" disabled={busy === j.id} onClick={() => act(j, 'cancel')}>
                      Cancel
                    </button>
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
