import { useEffect, useState } from 'react'
import { renderMarkdownBlock } from '../utils/renderMarkdown'
import { fetchReleaseNotes, markReleaseSeen } from '../utils/releaseNotes'
import type { ReleaseArea, ReleaseNotes } from '../utils/releaseNotes'

function when(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

function areaOf(path: string, areas: ReleaseArea[]): string {
  // Same rules as the backend's grouping, so a file lands under the area that counted it
  if (path.includes('.test.') || path.includes('/tests/') || path.startsWith('frontend/src/test')) return 'Tests'
  const prefixes: [string, string][] = [['backend/', 'Backend'], ['frontend/', 'Frontend'], ['desktop/', 'Desktop app'],
    ['deploy/', 'Deployment'], ['docs/', 'Docs'], ['sdk/', 'SDK'], ['examples/', 'Examples']]
  const hit = prefixes.find(([p]) => path.startsWith(p))?.[1] ?? 'Project'
  return areas.some((a) => a.area === hit) ? hit : 'Project'
}

/**
 * "What's new": what the latest commit released (GET /api/release-notes) — its message, and the files it
 * changed grouped by area. The top nav shows a dot until the newest commit has been opened once
 * (remembered per browser).
 */
export function WhatsNewPanel({ onClose, onSeen }: { onClose: () => void; onSeen?: (hash: string) => void }) {
  const [notes, setNotes] = useState<ReleaseNotes | null>(null)
  const [error, setError] = useState('')
  const [openArea, setOpenArea] = useState<string | null>(null)

  useEffect(() => {
    let current = true
    fetchReleaseNotes(1)
      .then((n) => {
        if (!current) return
        setNotes(n)
        if (n.commits[0]) { markReleaseSeen(n.commits[0].hash); onSeen?.(n.commits[0].hash) }
      })
      .catch((e) => { if (current) setError(e instanceof Error ? e.message : String(e)) })
    return () => { current = false }
  }, [onSeen])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const commit = notes?.commits[0]
  return (
    <div className="modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="modal-card wide whats-new-card" role="dialog" aria-modal="true" aria-labelledby="whats-new-title">
        <div className="modal-header">
          <h3 id="whats-new-title">What's new</h3>
          <button type="button" className="modal-close-btn" aria-label="Close" onClick={onClose}>✕</button>
        </div>
        <div className="whats-new-body">
          {error && <p className="whats-new-empty">Couldn't load the release notes: {error}</p>}
          {!error && !notes && <p className="whats-new-empty">Loading…</p>}
          {notes && !commit && (
            <p className="whats-new-empty">
              Release notes aren't available in this build. They're read from git, or from
              <code> release_notes.json</code> written by <code>backend/scripts/write_release_notes.py</code> before a build.
            </p>
          )}
          {commit && (
            <>
              <p className="whats-new-meta">
                Latest release · <time dateTime={commit.date}>{when(commit.date)}</time> · {commit.author} ·{' '}
                <code title={commit.hash}>{commit.short}</code>
              </p>
              <h4 className="whats-new-subject">{commit.subject}</h4>
              {commit.body && <div className="whats-new-message">{renderMarkdownBlock(commit.body)}</div>}

              {commit.areas.length > 0 && (
                <section className="whats-new-areas" aria-label="What changed">
                  <h5>What changed</h5>
                  <ul>
                    {commit.areas.map((a) => {
                      const files = commit.files.filter((f) => areaOf(f.path, commit.areas) === a.area)
                      const open = openArea === a.area
                      return (
                        <li key={a.area}>
                          <button type="button" className="whats-new-area" aria-expanded={open}
                            onClick={() => setOpenArea(open ? null : a.area)}>
                            <span className="whats-new-chevron" aria-hidden="true">{open ? '▾' : '▸'}</span>
                            <span className="whats-new-area-name">{a.area}</span>
                            <span className="whats-new-area-count">{a.files} file{a.files === 1 ? '' : 's'}</span>
                            <span className="whats-new-lines"><span className="whats-new-add">+{a.added}</span> <span className="whats-new-del">−{a.removed}</span></span>
                          </button>
                          {open && (
                            <ul className="whats-new-files">
                              {files.map((f) => (
                                <li key={f.path}>
                                  <code>{f.path}</code>
                                  <span className="whats-new-lines"><span className="whats-new-add">+{f.added}</span> <span className="whats-new-del">−{f.removed}</span></span>
                                </li>
                              ))}
                            </ul>
                          )}
                        </li>
                      )
                    })}
                  </ul>
                </section>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
