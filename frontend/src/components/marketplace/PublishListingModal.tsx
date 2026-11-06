import { useEffect, useState } from 'react'
import { API_BASE } from '../../types'
import type { AppRecord } from '../../types'
import { CATEGORY_LABELS, REQUIREMENT_ICONS, errorDetail, type Listing } from './types'
import '../../styles/marketplace.css'

interface Props {
  app: AppRecord
  onClose: () => void
  onPublished: (listing: Listing) => void
  /** Publish the draft app in place (saves the canvas first); offered when the app is a draft */
  onPublishApp?: () => Promise<void>
}

/** Publish a published app to the marketplace, or ship a new version of its listing. */
export function PublishListingModal({ app, onClose, onPublished, onPublishApp }: Props) {
  const [existing, setExisting] = useState<Listing | null | undefined>(undefined)
  const [summary, setSummary] = useState('')
  const [description, setDescription] = useState(app.description || '')
  const [category, setCategory] = useState('general')
  const [tags, setTags] = useState('')
  const [visibility, setVisibility] = useState<'public' | 'tenant'>('public')
  const [changelog, setChangelog] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<Listing | null>(null)

  useEffect(() => {
    fetch(`${API_BASE}/api/marketplace/listings?mine=1`)
      .then((r) => (r.ok ? r.json() : { listings: [] }))
      .then((d) => setExisting((d.listings as Listing[]).find((l) => l.source_app_id === app.id) ?? null))
      .catch(() => setExisting(null))
  }, [app.id])

  const submit = async () => {
    setBusy(true)
    setError('')
    try {
      const res = existing
        ? await fetch(`${API_BASE}/api/marketplace/listings/${existing.id}/versions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ changelog }),
        })
        : await fetch(`${API_BASE}/api/marketplace/listings`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            app_id: app.id, summary, description, category, visibility,
            tags: tags.split(',').map((t) => t.trim()).filter(Boolean),
            changelog: changelog || 'Initial release',
          }),
        })
      if (!res.ok) throw new Error(await errorDetail(res, 'Publishing failed'))
      const listing = await res.json()
      setResult(listing)
      onPublished(listing)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Publishing failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mkt-overlay" onClick={onClose}>
      <div className="mkt-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Publish to marketplace">
        <div className="mkt-modal-head">
          <h2>{existing ? `Publish v${existing.latest_version + 1} of “${existing.name}”` : 'Publish to marketplace'}</h2>
          <button type="button" className="mkt-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        {app.status !== 'published' ? (
          <div className="mkt-stack">
            <p className="mkt-note mkt-note--warn">
              “{app.name}” is a draft. Only published versions can go to the marketplace, so others get a
              stable snapshot{onPublishApp ? ' — publish it now to continue.' : '. Publish it first.'}
            </p>
            {error && <div className="mkt-note mkt-note--error" role="alert">{error}</div>}
            <div className="mkt-actions">
              <button type="button" className="mkt-btn" onClick={onClose}>Cancel</button>
              {onPublishApp && (
                <button
                  type="button"
                  className="mkt-btn mkt-btn--primary"
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true)
                    setError('')
                    try {
                      await onPublishApp()
                    } catch {
                      setError('Publishing the app failed')
                    } finally {
                      setBusy(false)
                    }
                  }}
                >
                  {busy ? 'Publishing…' : `🚀 Publish v${(app.version || 0) + 1} and continue`}
                </button>
              )}
            </div>
          </div>
        ) : existing === undefined ? (
          <p className="mkt-muted">Loading…</p>
        ) : result ? (
          <div className="mkt-stack">
            <p className="mkt-note mkt-note--ok">
              Listed as v{result.latest_version} · {result.visibility === 'public' ? 'visible to everyone' : 'visible to your tenant'}.
            </p>
            {result.requirements.length > 0 && (
              <>
                <div className="mkt-label">Importers will be asked to provide</div>
                <ul className="mkt-reqs">
                  {result.requirements.map((r, i) => (
                    <li key={i}><span>{REQUIREMENT_ICONS[r.kind]}</span><div><strong>{r.label}</strong><small>{r.detail}</small></div></li>
                  ))}
                </ul>
              </>
            )}
            <div className="mkt-actions"><button type="button" className="mkt-btn mkt-btn--primary" onClick={onClose}>Done</button></div>
          </div>
        ) : (
          <div className="mkt-stack">
            <p className="mkt-note">
              A snapshot of v{app.version} is shared. API keys, passwords, connection details, document
              collections and memory sessions are stripped; custom tool code is included so importers can review it.
            </p>
            {!existing && (
              <>
                <label className="mkt-field"><span>Summary</span>
                  <input value={summary} maxLength={200} onChange={(e) => setSummary(e.target.value)} placeholder="One line shown on the card" />
                </label>
                <label className="mkt-field"><span>Description</span>
                  <textarea rows={4} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What it does, inputs it expects, example prompts" />
                </label>
                <div className="mkt-row">
                  <label className="mkt-field"><span>Category</span>
                    <select value={category} onChange={(e) => setCategory(e.target.value)}>
                      {Object.entries(CATEGORY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                    </select>
                  </label>
                  <label className="mkt-field"><span>Visibility</span>
                    <select value={visibility} onChange={(e) => setVisibility(e.target.value as 'public' | 'tenant')}>
                      <option value="public">Public — every user</option>
                      <option value="tenant">My tenant only</option>
                    </select>
                  </label>
                </div>
                <label className="mkt-field"><span>Tags <em>(comma separated)</em></span>
                  <input value={tags} onChange={(e) => setTags(e.target.value)} placeholder="support, triage" />
                </label>
              </>
            )}
            <label className="mkt-field"><span>{existing ? 'What changed' : 'Release notes'} <em>(optional)</em></span>
              <input value={changelog} onChange={(e) => setChangelog(e.target.value)} placeholder={existing ? 'Better routing for refunds' : 'Initial release'} />
            </label>
            {error && <div className="mkt-note mkt-note--error" role="alert">{error}</div>}
            <div className="mkt-actions">
              <button type="button" className="mkt-btn" onClick={onClose}>Cancel</button>
              <button type="button" className="mkt-btn mkt-btn--primary" onClick={submit} disabled={busy}>
                {busy ? 'Publishing…' : existing ? `Publish v${existing.latest_version + 1}` : 'Publish'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
