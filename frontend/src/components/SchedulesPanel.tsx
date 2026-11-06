import { useCallback, useEffect, useMemo, useState } from 'react'
import { API_BASE } from '../types'
import { RETRY_NOTE, RetriesSelect, attemptLabel, retriesField } from './RetriesSelect'

interface PipelineRef {
  id: string
  name: string
  status?: 'draft' | 'published'
  version?: number
}

interface Schedule {
  id: string
  app_id: string
  app_name: string | null
  app_version: number
  app_status: string | null
  name: string
  cron: string
  timezone: string
  prompt: string
  enabled: boolean
  running: boolean
  timeout_ms: number
  max_failures: number
  retries: number
  consecutive_failures: number
  next_run_at: string | null
  last_run_at: string | null
  last_status: string | null
  last_error: string | null
}

interface ScheduleRun {
  id: string
  trigger: 'schedule' | 'manual'
  status: 'queued' | 'running' | 'retrying' | 'completed' | 'failed' | 'paused' | 'skipped' | 'interrupted'
  attempts: number
  app_version: number
  run_id: string | null
  output_preview: string | null
  error: string | null
  latency_ms: number
  cost_usd: number
  started_at: string
}

interface Props {
  /** Pipelines to choose from (Monitor). Ignored when `fixedApp` is set. */
  apps: PipelineRef[]
  /** Build sidebar: show and create schedules for this pipeline only. */
  fixedApp?: PipelineRef | null
  compact?: boolean
}

// ── Cadence presets ⇄ cron ───────────────────────────────────────────────────

type Mode = 'hourly' | 'daily' | 'weekdays' | 'weekly' | 'custom'
const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

interface Cadence { mode: Mode; time: string; minute: string; weekday: string; custom: string }

const pad = (n: string | number) => String(n).padStart(2, '0')

function toCron(c: Cadence): string {
  const [h, m] = c.time.split(':').map((x) => String(parseInt(x, 10) || 0))
  switch (c.mode) {
    case 'hourly':   return `${parseInt(c.minute, 10) || 0} * * * *`
    case 'daily':    return `${m} ${h} * * *`
    case 'weekdays': return `${m} ${h} * * 1-5`
    case 'weekly':   return `${m} ${h} * * ${c.weekday}`
    default:         return c.custom.trim()
  }
}

function fromCron(cron: string): Cadence {
  const base: Cadence = { mode: 'custom', time: '09:00', minute: '0', weekday: '1', custom: cron }
  const f = cron.trim().split(/\s+/)
  if (f.length !== 5 || f[2] !== '*' || f[3] !== '*') return base
  const [m, h, , , dow] = f
  if (!/^\d+$/.test(m)) return base
  if (h === '*' && dow === '*') return { ...base, mode: 'hourly', minute: m }
  if (!/^\d+$/.test(h)) return base
  const time = `${pad(h)}:${pad(m)}`
  if (dow === '*') return { ...base, mode: 'daily', time }
  if (dow === '1-5') return { ...base, mode: 'weekdays', time }
  if (/^[0-6]$/.test(dow)) return { ...base, mode: 'weekly', time, weekday: dow }
  return base
}

function describeCron(cron: string): string {
  const c = fromCron(cron)
  switch (c.mode) {
    case 'hourly':   return `Hourly at :${pad(c.minute)}`
    case 'daily':    return `Daily at ${c.time}`
    case 'weekdays': return `Weekdays at ${c.time}`
    case 'weekly':   return `${DAYS[Number(c.weekday)]}s at ${c.time}`
    default:         return cron
  }
}

// ── Time formatting ──────────────────────────────────────────────────────────

function relative(iso: string): string {
  const s = Math.round((new Date(iso).getTime() - Date.now()) / 1000)
  const a = Math.abs(s)
  const v = a < 60 ? `${a}s` : a < 3600 ? `${Math.round(a / 60)}m` : a < 86400 ? `${Math.round(a / 3600)}h` : `${Math.round(a / 86400)}d`
  return s >= 0 ? `in ${v}` : `${v} ago`
}

const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })

function browserTimezone(): string {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' } catch { return 'UTC' }
}

function allTimezones(): string[] {
  try { return (Intl as unknown as { supportedValuesOf(k: string): string[] }).supportedValuesOf('timeZone') } catch { return ['UTC'] }
}

async function errorText(r: Response): Promise<string> {
  const d = await r.json().catch(() => ({}))
  return typeof d.detail === 'string' ? d.detail : r.statusText
}

// ── Form ─────────────────────────────────────────────────────────────────────

interface FormState extends Cadence {
  app_id: string
  name: string
  timezone: string
  prompt: string
  timeout_s: string
  max_failures: string
  retries: string
}

function emptyForm(appId: string): FormState {
  return {
    app_id: appId, name: '', timezone: browserTimezone(), prompt: '', timeout_s: '120', max_failures: '3', retries: '',
    mode: 'daily', time: '09:00', minute: '0', weekday: '1', custom: '0 9 * * *',
  }
}

function formFrom(s: Schedule): FormState {
  return {
    ...fromCron(s.cron), app_id: s.app_id, name: s.name, timezone: s.timezone, prompt: s.prompt,
    timeout_s: String(Math.round(s.timeout_ms / 1000)), max_failures: String(s.max_failures),
    retries: String(s.retries),
  }
}

function ScheduleForm({ initial, editingId, pipelines, fixed, onCancel, onSaved }: {
  initial: FormState
  editingId: string | null
  pipelines: PipelineRef[]
  fixed: boolean
  onCancel: () => void
  onSaved: () => void
}) {
  const [f, setF] = useState<FormState>(initial)
  const [preview, setPreview] = useState<string[]>([])
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const timezones = useMemo(allTimezones, [])
  const cron = toCron(f)
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }))

  // Validate + preview the next firings as the cadence changes
  useEffect(() => {
    if (!cron) { setPreview([]); setPreviewError(null); return }
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`${API_BASE}/api/schedules/preview`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ cron, timezone: f.timezone || 'UTC' }),
        })
        if (!r.ok) { setPreview([]); setPreviewError(await errorText(r)); return }
        setPreview(((await r.json()).next_runs as string[]).slice(0, 3))
        setPreviewError(null)
      } catch (e) {
        setPreviewError(e instanceof Error ? e.message : String(e))
      }
    }, 300)
    return () => clearTimeout(t)
  }, [cron, f.timezone])

  const save = async () => {
    if (!f.app_id) { setError('Pick a pipeline.'); return }
    if (!f.prompt.trim()) { setError('Enter the prompt each run sends.'); return }
    setSaving(true)
    setError(null)
    const body = {
      name: f.name, cron, timezone: f.timezone || 'UTC', prompt: f.prompt,
      timeout_ms: Math.max(1, parseInt(f.timeout_s, 10) || 120) * 1000,
      max_failures: Math.max(0, parseInt(f.max_failures, 10) || 0),
      retries: retriesField(f.retries),
    }
    try {
      const r = editingId
        ? await fetch(`${API_BASE}/api/schedules/${encodeURIComponent(editingId)}`, {
            method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
          })
        : await fetch(`${API_BASE}/api/schedules`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...body, app_id: f.app_id }),
          })
      if (!r.ok) { setError(await errorText(r)); return }
      onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  const publishable = pipelines.filter((p) => (p.version ?? 0) > 0)

  return (
    <div className="sched-form">
      {!fixed && !editingId && (
        <label className="sched-field">
          <span>Pipeline</span>
          <select className="ops-select" value={f.app_id} onChange={(e) => set('app_id', e.target.value)}>
            <option value="">Select a published pipeline…</option>
            {publishable.map((p) => <option key={p.id} value={p.id}>{p.name} (v{p.version})</option>)}
          </select>
        </label>
      )}

      <label className="sched-field">
        <span>Name</span>
        <input className="sched-input" value={f.name} placeholder="e.g. Morning sales digest"
               onChange={(e) => set('name', e.target.value)} />
      </label>

      <div className="sched-field">
        <span>Runs</span>
        <div className="sched-cadence">
          <select className="ops-select" value={f.mode} onChange={(e) => set('mode', e.target.value as Mode)}>
            <option value="hourly">Every hour</option>
            <option value="daily">Every day</option>
            <option value="weekdays">Weekdays</option>
            <option value="weekly">Every week</option>
            <option value="custom">Custom (cron)</option>
          </select>
          {f.mode === 'weekly' && (
            <select className="ops-select" value={f.weekday} onChange={(e) => set('weekday', e.target.value)}>
              {DAYS.map((d, i) => <option key={d} value={String(i)}>{d}</option>)}
            </select>
          )}
          {f.mode === 'hourly' && (
            <label className="sched-inline">
              at minute
              <input className="sched-input sched-input--num" type="number" min={0} max={59} value={f.minute}
                     onChange={(e) => set('minute', e.target.value)} />
            </label>
          )}
          {(f.mode === 'daily' || f.mode === 'weekdays' || f.mode === 'weekly') && (
            <input className="sched-input sched-input--time" type="time" value={f.time}
                   onChange={(e) => set('time', e.target.value || '00:00')} />
          )}
          {f.mode === 'custom' && (
            <input className="sched-input sched-input--mono" value={f.custom} placeholder="*/30 * * * *"
                   onChange={(e) => set('custom', e.target.value)} />
          )}
        </div>
      </div>

      <label className="sched-field">
        <span>Timezone</span>
        <input className="sched-input" list="sched-timezones" value={f.timezone}
               onChange={(e) => set('timezone', e.target.value)} />
        <datalist id="sched-timezones">
          {timezones.map((tz) => <option key={tz} value={tz} />)}
        </datalist>
      </label>

      <div className={`sched-preview${previewError ? ' sched-preview--error' : ''}`}>
        {previewError
          ? previewError
          : preview.length > 0 && <>Next: {preview.map(when).join(' · ')} <span className="sched-muted">(your local time)</span></>}
      </div>

      <label className="sched-field">
        <span>Prompt</span>
        <textarea className="sched-input sched-textarea" rows={3} value={f.prompt}
                  placeholder="What each run should do, e.g. Summarize yesterday's orders and flag anomalies."
                  onChange={(e) => set('prompt', e.target.value)} />
      </label>

      <details className="sched-advanced">
        <summary>Advanced</summary>
        <div className="sched-advanced-row">
          <label className="sched-inline">
            Timeout
            <input className="sched-input sched-input--num" type="number" min={1} max={600} value={f.timeout_s}
                   onChange={(e) => set('timeout_s', e.target.value)} />
            s
          </label>
          <label className="sched-inline">
            Pause after
            <input className="sched-input sched-input--num" type="number" min={0} max={100} value={f.max_failures}
                   onChange={(e) => set('max_failures', e.target.value)} />
            failures in a row (0 = never)
          </label>
          <RetriesSelect value={f.retries} onChange={(v) => set('retries', v)} allowDefault={!editingId} />
        </div>
        <p className="sched-muted">{RETRY_NOTE} A firing counts once toward "pause after", after its last attempt.</p>
        <p className="sched-muted">
          Scheduled runs use API keys set on the pipeline's nodes or the server's environment — keys saved only in
          this browser aren't available to them.
        </p>
      </details>

      {error && <div className="sched-error">{error}</div>}

      <div className="sched-form-actions">
        <button type="button" className="docs-btn" onClick={onCancel} disabled={saving}>Cancel</button>
        <button type="button" className="docs-btn docs-btn--primary" onClick={save}
                disabled={saving || !!previewError || !cron}>
          {saving ? 'Saving…' : editingId ? 'Save changes' : 'Create schedule'}
        </button>
      </div>
    </div>
  )
}

// ── Run history ──────────────────────────────────────────────────────────────

function RunHistory({ scheduleId, refreshKey, retries }: { scheduleId: string; refreshKey: number; retries: number }) {
  const [runs, setRuns] = useState<ScheduleRun[] | null>(null)
  const [open, setOpen] = useState<string | null>(null)

  useEffect(() => {
    fetch(`${API_BASE}/api/schedules/${encodeURIComponent(scheduleId)}/runs?limit=20`)
      .then((r) => (r.ok ? r.json() : []))
      .then(setRuns)
      .catch(() => setRuns([]))
  }, [scheduleId, refreshKey])

  if (runs === null) return <div className="sched-runs sched-muted">Loading…</div>
  if (runs.length === 0) return <div className="sched-runs sched-muted">No runs yet.</div>

  return (
    <div className="sched-runs">
      {runs.map((r) => (
        <div key={r.id} className="sched-run">
          <button type="button" className="sched-run-row" onClick={() => setOpen(open === r.id ? null : r.id)}>
            <span className={`sched-dot sched-dot--${r.status}`} title={r.status} />
            <span className="sched-run-status">{r.status}</span>
            <span className="sched-muted">{r.trigger === 'manual' ? 'manual' : 'scheduled'}{r.app_version ? ` · v${r.app_version}` : ''}</span>
            <span className="sched-run-time">{when(r.started_at)}</span>
            {attemptLabel(r.attempts, retries) && <span className="sched-muted">{attemptLabel(r.attempts, retries)}</span>}
            {r.latency_ms > 0 && <span className="sched-muted">{(r.latency_ms / 1000).toFixed(1)}s</span>}
          </button>
          {open === r.id && (
            <div className="sched-run-detail">
              {r.error && <div className="sched-error">{r.error}</div>}
              {r.output_preview && <pre className="sched-output">{r.output_preview}</pre>}
              {r.run_id && <div className="sched-muted">Trace run id: <code>{r.run_id}</code></div>}
              {!r.error && !r.output_preview && <div className="sched-muted">No output recorded.</div>}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

// ── Panel ────────────────────────────────────────────────────────────────────

/** Cron schedules for published pipelines: list, create, pause, run now, history. */
export function SchedulesPanel({ apps, fixedApp, compact }: Props) {
  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState<{ initial: FormState; editingId: string | null } | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)

  const fixed = fixedApp !== undefined
  const appId = fixedApp?.id ?? ''

  const load = useCallback(() => {
    if (fixed && !appId) { setSchedules([]); return }
    setLoading(true)
    const qs = appId ? `?app_id=${encodeURIComponent(appId)}` : ''
    fetch(`${API_BASE}/api/schedules${qs}`)
      .then(async (r) => (r.ok ? r.json() : Promise.reject(new Error(await errorText(r)))))
      .then((d: Schedule[]) => { setSchedules(d); setError(null) })
      .catch((e) => setError(`Failed to load schedules: ${e.message}`))
      .finally(() => { setLoading(false); setRefreshKey((k) => k + 1) })
  }, [fixed, appId])

  useEffect(() => { load(); setForm(null); setExpanded(null) }, [load])

  // Poll while something is running so status and history settle on their own
  const anyRunning = schedules.some((s) => s.running)
  useEffect(() => {
    if (!anyRunning) return
    const t = setInterval(load, 3000)
    return () => clearInterval(t)
  }, [anyRunning, load])

  const act = async (url: string, init: RequestInit) => {
    try {
      const r = await fetch(url, init)
      if (!r.ok) { setError(await errorText(r)); return }
      setError(null)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const patch = (s: Schedule, body: Record<string, unknown>) =>
    act(`${API_BASE}/api/schedules/${encodeURIComponent(s.id)}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    })

  const runNow = (s: Schedule) => {
    setExpanded(s.id)
    act(`${API_BASE}/api/schedules/${encodeURIComponent(s.id)}/run`, { method: 'POST' })
  }

  const remove = (s: Schedule) => {
    if (!window.confirm(`Delete "${s.name}" and its run history?`)) return
    act(`${API_BASE}/api/schedules/${encodeURIComponent(s.id)}`, { method: 'DELETE' })
  }

  // Build sidebar: explain why scheduling isn't available yet
  const blocked = fixed && (!fixedApp
    ? 'Save and publish this pipeline to schedule it.'
    : !(fixedApp.version ?? 0)
      ? 'Publish this pipeline to schedule it — only published versions run on a schedule.'
      : null)
  const draftNote = fixed && fixedApp && (fixedApp.version ?? 0) > 0 && fixedApp.status === 'draft'
    ? `Scheduled runs use v${fixedApp.version}, the latest published version. Publish to include your current edits.`
    : null

  return (
    <div className={`sched-panel${compact ? ' sched-panel--compact' : ' ops-panel'}`}>
      <div className={compact ? 'sched-toolbar' : 'ops-toolbar'}>
        <div className="ops-toolbar-left">
          {!compact && <span className="ops-panel-title">Schedules</span>}
          <span className="ops-count-badge">{schedules.length} schedule{schedules.length !== 1 ? 's' : ''}</span>
        </div>
        <div className="ops-toolbar-right">
          <button type="button" className="ops-refresh-btn" onClick={load} disabled={loading || !!blocked}>
            {loading ? '…' : '↻'}
          </button>
          <button type="button" className="docs-btn docs-btn--primary" disabled={!!blocked || !!form}
                  onClick={() => setForm({ initial: emptyForm(appId), editingId: null })}>
            + New schedule
          </button>
        </div>
      </div>

      <div className="sched-body">
        {blocked && <div className="sched-empty">{blocked}</div>}
        {draftNote && <div className="sched-note">{draftNote}</div>}
        {error && <div className="sched-error">{error}</div>}

        {form && (
          <ScheduleForm
            key={form.editingId ?? 'new'}
            initial={form.initial}
            editingId={form.editingId}
            pipelines={apps}
            fixed={fixed}
            onCancel={() => setForm(null)}
            onSaved={() => { setForm(null); load() }}
          />
        )}

        {!blocked && !form && schedules.length === 0 && !loading && (
          <div className="sched-empty">
            <p className="sched-empty-title">No schedules yet</p>
            <p className="sched-muted">
              Run a published pipeline automatically — a nightly report, an hourly check, a weekly digest. Each run
              sends a fixed prompt and is recorded with its output.
            </p>
          </div>
        )}

        {schedules.map((s) => {
          const autoPaused = !s.enabled && (s.last_error ?? '').startsWith('Paused after')
          const state = s.running ? 'running' : s.enabled ? 'active' : autoPaused ? 'auto-paused' : 'paused'
          return (
            <div key={s.id} className={`sched-card sched-card--${state}`}>
              <div className="sched-card-head">
                <div className="sched-card-title">
                  <span className="sched-card-name">{s.name}</span>
                  <span className={`sched-pill sched-pill--${state}`}>{state.replace('-', ' ')}</span>
                </div>
                {!fixed && (
                  <div className="sched-muted">
                    {s.app_name ?? 'Deleted pipeline'}{s.app_version ? ` · v${s.app_version}` : ''}
                  </div>
                )}
                <div className="sched-card-cadence">
                  <span>{describeCron(s.cron)}</span>
                  <span className="sched-muted">{s.timezone}</span>
                  <code className="sched-cron">{s.cron}</code>
                </div>
                <div className="sched-card-meta">
                  {s.enabled && s.next_run_at && (
                    <span title={when(s.next_run_at)}>Next {relative(s.next_run_at)}</span>
                  )}
                  {s.last_run_at && (
                    <span title={when(s.last_run_at)}>
                      Last {relative(s.last_run_at)}
                      {s.last_status && <span className={`sched-dot sched-dot--${s.last_status}`} title={s.last_status} />}
                    </span>
                  )}
                  {!s.last_run_at && <span className="sched-muted">Never run</span>}
                </div>
                {s.last_error && <div className="sched-error sched-error--inline">{s.last_error}</div>}
                <div className="sched-prompt" title={s.prompt}>“{s.prompt}”</div>
              </div>

              <div className="sched-actions">
                <button type="button" className="docs-btn" onClick={() => runNow(s)} disabled={s.running}>
                  {s.running ? 'Running…' : '▶ Run now'}
                </button>
                <button type="button" className="docs-btn" onClick={() => patch(s, { enabled: !s.enabled })}>
                  {s.enabled ? 'Pause' : 'Resume'}
                </button>
                <button type="button" className="docs-btn" disabled={!!form}
                        onClick={() => setForm({ initial: formFrom(s), editingId: s.id })}>
                  Edit
                </button>
                <button type="button" className="docs-btn" onClick={() => setExpanded(expanded === s.id ? null : s.id)}>
                  {expanded === s.id ? 'Hide history' : 'History'}
                </button>
                <button type="button" className="docs-btn sched-delete" onClick={() => remove(s)}>Delete</button>
              </div>

              {expanded === s.id && <RunHistory scheduleId={s.id} refreshKey={refreshKey} retries={s.retries} />}
            </div>
          )
        })}
      </div>
    </div>
  )
}
