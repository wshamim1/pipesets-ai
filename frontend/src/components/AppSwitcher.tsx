import { useEffect, useRef, useState } from 'react'
import type { AppRecord } from '../types'

interface Props {
  currentApp: AppRecord | null
  apps: AppRecord[]
  onOpenApp: (app: AppRecord) => void
  onManageApps: () => void
  onNewApp: () => void
}

const RECENT_LIMIT = 6

/** App name in the canvas header, doubling as the switcher: recent apps, all apps, new app. */
export function AppSwitcher({ currentApp, apps, onOpenApp, onManageApps, onNewApp }: Props) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const recent = [...apps]
    .sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''))
    .slice(0, RECENT_LIMIT)

  const choose = (fn: () => void) => () => { setOpen(false); fn() }

  return (
    <div className="app-switcher" ref={wrapRef}>
      <button
        type="button"
        className="app-switcher-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        title="Switch app"
      >
        <strong className="canvas-heading-title">{currentApp?.name || 'Untitled pipeline'}</strong>
        <span className="app-switcher-caret" aria-hidden="true">▾</span>
      </button>

      {open && (
        <div className="app-switcher-menu" role="menu">
          {recent.length > 0 && <div className="app-switcher-label">Recent apps</div>}
          {recent.map((app) => (
            <button
              key={app.id}
              type="button"
              role="menuitem"
              className={`app-switcher-item${currentApp?.id === app.id ? ' app-switcher-item--current' : ''}`}
              onClick={choose(() => onOpenApp(app))}
            >
              <span className="app-switcher-item-name">{app.name}</span>
              <span className={`app-switcher-status app-switcher-status--${app.status ?? 'draft'}`}>
                {app.status === 'published' ? `v${app.version}` : 'Draft'}
              </span>
            </button>
          ))}
          <div className="app-switcher-sep" />
          <button type="button" role="menuitem" className="app-switcher-item" onClick={choose(onManageApps)}>
            All apps…
          </button>
          <button type="button" role="menuitem" className="app-switcher-item app-switcher-item--accent" onClick={choose(onNewApp)}>
            + New app
          </button>
        </div>
      )}
    </div>
  )
}
