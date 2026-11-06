// "Retry failed runs" picker for schedules and webhooks. The API stores a number of retries
// after the first attempt: 0–10, or -1 to keep retrying until a run succeeds. '' leaves it to
// the server default (JOB_MAX_RETRIES) on create.

const OPTIONS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

export function RetriesSelect({ value, onChange, allowDefault }: {
  value: string
  onChange: (v: string) => void
  allowDefault: boolean
}) {
  return (
    <label className="sched-inline">
      Retry failed runs
      <select className="sched-input" value={value} onChange={(e) => onChange(e.target.value)}>
        {allowDefault && <option value="">Server default</option>}
        <option value="0">Never</option>
        {OPTIONS.slice(1).map((n) => <option key={n} value={String(n)}>{n} {n === 1 ? 'time' : 'times'}</option>)}
        <option value="-1">Until it succeeds</option>
      </select>
    </label>
  )
}

/** The request field for a picker value; undefined lets the server default apply. */
export function retriesField(value: string): number | undefined {
  return value === '' ? undefined : parseInt(value, 10)
}

/** "attempt 2", "attempt 2 of 3" — shown on runs that needed more than one. */
export function attemptLabel(attempts: number | undefined, retries: number | undefined): string {
  if (!attempts || attempts < 2) return ''
  return retries !== undefined && retries >= 0 ? `attempt ${attempts} of ${retries + 1}` : `attempt ${attempts}`
}

export const RETRY_NOTE = 'Failed or interrupted runs are retried with a growing delay (30 s, 2 min, 8 min … up to an hour). '
  + 'Runs blocked by a guardrail or budget, or rejected at a Human Gate, are not retried.'
