import { useEffect, useState } from 'react'
import { FRONTEND_BUILD, fetchAbout } from '../utils/about'
import type { Library, ServerAbout } from '../utils/about'

const DB_NAMES: Record<string, string> = { sqlite: 'SQLite', postgresql: 'PostgreSQL', mysql: 'MySQL' }

function when(iso: string): string {
  const d = new Date(iso)
  return !iso || Number.isNaN(d.getTime()) ? '' : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

function Rows({ rows }: { rows: [string, React.ReactNode, string?][] }) {
  return (
    <dl className="about-rows">
      {rows.filter(([, v]) => v !== '' && v !== null && v !== undefined).map(([k, v, hint]) => (
        <div key={k} className="about-row">
          <dt>{k}</dt>
          <dd>{v}{hint && <span className="about-hint"> · {hint}</span>}</dd>
        </div>
      ))}
    </dl>
  )
}

const libRows = (libs: Library[]): [string, React.ReactNode, string?][] =>
  libs.map((l) => [l.name, <code key={l.name}>{l.version}</code>, l.role])

/** About Pipesets: version and commit, what the frontend and backend are built with, the database and the catalog. */
export function AboutPanel({ onClose }: { onClose: () => void }) {
  const [about, setAbout] = useState<ServerAbout | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let current = true
    fetchAbout().then((a) => { if (current) setAbout(a) })
      .catch((e) => { if (current) setError(e instanceof Error ? e.message : String(e)) })
    return () => { current = false }
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const commit = about?.app.commit
  const db = about?.backend.database
  return (
    <div className="modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="modal-card wide about-card" role="dialog" aria-modal="true" aria-labelledby="about-title">
        <div className="modal-header">
          <h3 id="about-title">About Pipesets AI</h3>
          <button type="button" className="modal-close-btn" aria-label="Close" onClick={onClose}>✕</button>
        </div>
        <div className="about-body">
          {error && <p className="about-error">Couldn't reach the backend: {error}. The frontend details below are from this browser's bundle.</p>}
          {!about && !error && <p className="about-hint">Loading…</p>}

          {about && (
            <section aria-label="Version">
              <h4>Version</h4>
              <Rows rows={[
                ['Pipesets', <strong key="v">{about.app.version}</strong>],
                ['Commit', commit ? <><code title={commit.hash}>{commit.short}</code> {commit.subject}</> : 'not available in this build',
                  commit ? when(commit.date) : undefined],
                ['License', about.app.license],
              ]} />
            </section>
          )}

          <section aria-label="Frontend">
            <h4>Frontend</h4>
            <Rows rows={[...libRows(FRONTEND_BUILD.libraries), ['Built', when(FRONTEND_BUILD.builtAt)]]} />
          </section>

          {about && (
            <section aria-label="Backend">
              <h4>Backend</h4>
              <Rows rows={[
                ['Python', <code key="py">{about.backend.python}</code>, `${about.backend.implementation}${about.backend.frozen ? ', desktop build' : ''}`],
                ...libRows(about.backend.libraries),
                ['Database', db ? <>{DB_NAMES[db.type] ?? db.type} <code>{db.version}</code></> : '', db?.driver],
                ['Model backends', about.backend.llm_backends.join(', ')],
                ['Server', about.backend.platform],
              ]} />
            </section>
          )}

          {about && (
            <section aria-label="Built-in catalog">
              <h4>Built in</h4>
              <Rows rows={[
                ['Tools', about.catalog.tools], ['MCP servers', about.catalog.mcp_servers],
                ['Frameworks', about.catalog.frameworks],
                ['Agents', about.catalog.agents, `plus ${about.catalog.starter_roles} starter roles`],
                ['Skills', about.catalog.skills],
              ]} />
            </section>
          )}
        </div>
      </div>
    </div>
  )
}
