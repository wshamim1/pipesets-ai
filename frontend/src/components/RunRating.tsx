/**
 * 👍 / 👎 on a finished run in the Prompt Runner (backend routers/feedback.py, plan.md F2). The
 * rating is the builder's own; it shows up next to chat-link and API ratings under Evaluate →
 * Feedback, where 👎 ones can be turned into eval cases. After a 👎, an optional note says what was
 * wrong and what the answer should have been.
 */
import { useEffect, useState } from 'react'
import { API_BASE } from '../types'

type Rating = 1 | -1

export function RunRating({ runId }: { runId: string }) {
  const [rating, setRating] = useState<Rating | null>(null)
  const [noteOpen, setNoteOpen] = useState(false)
  const [comment, setComment] = useState('')
  const [correction, setCorrection] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    let live = true
    fetch(`${API_BASE}/api/feedback/runs/${encodeURIComponent(runId)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((fb) => {
        if (!live || !fb) return
        setRating(fb.rating)
        setComment(fb.comment ?? '')
        setCorrection(fb.correction ?? '')
      })
      .catch(() => {})
    return () => { live = false }
  }, [runId])

  const save = async (next: Rating | null, note = { comment, correction }) => {
    const before = rating
    setRating(next)
    setError('')
    const url = `${API_BASE}/api/feedback/runs/${encodeURIComponent(runId)}`
    const res = await (next === null
      ? fetch(url, { method: 'DELETE' })
      : fetch(url, { method: 'PUT', headers: { 'Content-Type': 'application/json' },
                     body: JSON.stringify({ rating: next, ...note }) })).catch(() => null)
    if (!res || !res.ok) {
      setRating(before)
      const body = res ? await res.json().catch(() => ({})) : {}
      setError(typeof body.detail === 'string' ? body.detail : 'Not saved')
    }
  }

  // Clicking the active thumb takes the rating back
  const click = (r: Rating) => {
    setNoteOpen(r === -1 && rating !== -1)
    void save(rating === r ? null : r)
  }

  return (
    <span className="run-rating">
      <button type="button" className={`run-rating-btn${rating === 1 ? ' run-rating-btn--on' : ''}`}
        aria-pressed={rating === 1} title="Good answer" onClick={() => click(1)}>👍</button>
      <button type="button" className={`run-rating-btn${rating === -1 ? ' run-rating-btn--on' : ''}`}
        aria-pressed={rating === -1} title="Bad answer — add what was wrong" onClick={() => click(-1)}>👎</button>
      {rating === -1 && !noteOpen && (
        <button type="button" className="run-rating-link" onClick={() => setNoteOpen(true)}>
          {comment || correction ? 'Edit note' : 'Add note'}
        </button>
      )}
      {error && <span className="run-rating-error">{error}</span>}
      {noteOpen && rating === -1 && (
        <form className="run-rating-note" onSubmit={(e) => {
          e.preventDefault()
          setNoteOpen(false)
          void save(-1, { comment: comment.trim(), correction: correction.trim() })
        }}>
          <input className="run-rating-input" value={comment} maxLength={4000} placeholder="What was wrong?"
            aria-label="What was wrong" onChange={(e) => setComment(e.target.value)} />
          <textarea className="run-rating-input" value={correction} rows={2} maxLength={20000}
            placeholder="What should it have said? (becomes the expected output when exported to evals)"
            aria-label="Expected answer" onChange={(e) => setCorrection(e.target.value)} />
          <span className="run-rating-actions">
            <button type="submit" className="run-rating-save">Save</button>
            <button type="button" className="run-rating-link" onClick={() => setNoteOpen(false)}>Cancel</button>
          </span>
        </form>
      )}
    </span>
  )
}
