import { useState, useEffect, useRef, useCallback } from 'react'
import { BookOpen, Bug, ChevronDown, CircleHelp, Info, Keyboard, Lightbulb, Megaphone, Settings } from 'lucide-react'
import { useCredentials } from '../context/CredentialsContext'
import type { AuthUser } from '../context/AuthContext'
import '../styles/auth.css'
import { useSecrets } from '../utils/secrets'
import { WhatsNewPanel } from './WhatsNewPanel'
import { AboutPanel } from './AboutPanel'
import { KeyboardShortcutsPanel } from './KeyboardShortcutsPanel'
import { FRONTEND_BUILD, fetchAbout } from '../utils/about'
import { fetchReleaseNotes, lastSeenRelease } from '../utils/releaseNotes'

import type { TopView, MonitorTab, AutomationTab, SettingsTab } from '../utils/appUrl'

// Lifecycle first (pick an app → build → test → watch it run), then discovery.
const VIEW_GROUPS: { id: TopView; label: string }[][] = [
  [
    { id: 'apps', label: 'Apps' },
    { id: 'build', label: 'Build' },
    { id: 'evaluate', label: 'Evaluate' },
    { id: 'monitor', label: 'Monitor' },
    { id: 'automation', label: 'Automation' },
  ],
  [
    { id: 'marketplace', label: 'Marketplace' },
    { id: 'lab', label: 'Lab' },
  ],
]

const REPO_URL = 'https://github.com/wshamim1/pipesets-ai'

/** A new GitHub issue, pre-filled with where the user was and what build they run. Opened synchronously so pop-up blockers allow it. */
function openIssue(kind: 'bug' | 'idea', view: TopView, commit: string) {
  const env = [
    `- Page: ${view}`,
    commit && `- Commit: ${commit}`,
    FRONTEND_BUILD.builtAt && `- Frontend built: ${FRONTEND_BUILD.builtAt}`,
    `- Browser: ${navigator.userAgent}`,
  ].filter(Boolean).join('\n')
  const body = kind === 'bug'
    ? `**What happened**\n\n\n**What you expected**\n\n\n**Steps to reproduce**\n1. \n\n**Environment**\n${env}\n`
    : `**The idea**\n\n\n**Why it would help**\n\n\n**Environment**\n${env}\n`
  const params = new URLSearchParams({ body, labels: kind === 'bug' ? 'bug' : 'enhancement' })
  window.open(`${REPO_URL}/issues/new?${params}`, '_blank', 'noopener')
}

/** Close a popover on outside click or Escape. */
function useDismiss(open: boolean, ref: React.RefObject<HTMLElement | null>, close: () => void) {
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) close()
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close() }
    document.addEventListener('mousedown', handler)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', handler)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, ref, close])
}

const MONITOR_TABS: { id: MonitorTab; label: string }[] = [
  { id: 'metrics', label: 'Metrics' },
  { id: 'runs', label: 'Runs' },
  { id: 'traces', label: 'Traces' },
  { id: 'logs', label: 'Logs' },
  { id: 'costs', label: 'Costs & budgets' },
  { id: 'sessions', label: 'Sessions' },
]

// What runs unattended, and the queue that runs it
const AUTOMATION_TABS: { id: AutomationTab; label: string }[] = [
  { id: 'schedules', label: 'Schedules' },
  { id: 'webhooks', label: 'Webhooks' },
  { id: 'batches', label: 'Batches' },
  { id: 'alerts', label: 'Alerts' },
  { id: 'jobs', label: 'Jobs' },
]

interface Props {
  view: TopView
  monitorTab: MonitorTab
  automationTab: AutomationTab
  onViewChange: (v: TopView) => void
  onMonitorTabChange: (t: MonitorTab) => void
  onAutomationTabChange: (t: AutomationTab) => void
  onOpenSettings: (tab: SettingsTab) => void
  tenantId: string
  tenants: Array<{ id: string; name: string }>
  projectId: string
  user: AuthUser | null
  projects: Array<{ id: string; name: string }>
  onTenantChange: (tenantId: string) => void
  onProjectChange: (projectId: string) => void
  onLogout: () => void
}

export function TopNav({
  view,
  monitorTab,
  automationTab,
  onViewChange,
  onMonitorTabChange,
  onAutomationTabChange,
  onOpenSettings,
  tenantId,
  tenants,
  projectId,
  user,
  projects,
  onTenantChange,
  onProjectChange,
  onLogout,
}: Props) {
  const { credentials } = useCredentials()
  const { secrets } = useSecrets()
  const keyCount = Object.values(credentials).filter((v) => v.trim().length > 0).length
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const [whatsNewOpen, setWhatsNewOpen] = useState(false)
  const [aboutOpen, setAboutOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const helpRef = useRef<HTMLDivElement>(null)
  const [shortcutsOpen, setShortcutsOpen] = useState(false)
  const [commit, setCommit] = useState('')

  // Fetched when Help opens, so a bug report carries the build without delaying the click
  useEffect(() => {
    if (!helpOpen || commit) return
    let current = true
    fetchAbout().then((a) => { if (current) setCommit(a.app.commit?.short ?? '') }, () => { /* report without it */ })
    return () => { current = false }
  }, [helpOpen, commit])
  // The newest release's commit, while it hasn't been opened in this browser (the button shows a dot)
  const [unseenRelease, setUnseenRelease] = useState('')

  useEffect(() => {
    let current = true
    fetchReleaseNotes(1)
      .then((n) => { const hash = n.commits[0]?.hash; if (current && hash && hash !== lastSeenRelease()) setUnseenRelease(hash) })
      .catch(() => { /* no notes: no dot */ })
    return () => { current = false }
  }, [])
  const onReleaseSeen = useCallback(() => setUnseenRelease(''), [])

  const closeMenu = useCallback(() => setMenuOpen(false), [])
  const closeHelp = useCallback(() => setHelpOpen(false), [])
  useDismiss(menuOpen, menuRef, closeMenu)
  useDismiss(helpOpen, helpRef, closeHelp)

  // "?" opens the shortcuts list, unless the user is typing
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '?' || e.metaKey || e.ctrlKey || e.altKey) return
      const el = document.activeElement as HTMLElement | null
      if (el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return
      e.preventDefault()
      setShortcutsOpen(true)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const helpAction = (fn: () => void) => () => { setHelpOpen(false); fn() }

  const openSettings = (tab: SettingsTab) => {
    setMenuOpen(false)
    onOpenSettings(tab)
  }

  const tenantOptions = tenants.some((t) => t.id === tenantId)
    ? tenants
    : [{ id: tenantId, name: `${tenantId} (current)` }, ...tenants]

  const projectOptions = projects.some((p) => p.id === projectId)
    ? projects
    : [{ id: projectId, name: `${projectId} (current)` }, ...projects]

  const userLabel = user?.display_name || user?.email || ''
  const initials = userLabel
    .split(/[\s@._-]+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join('') || '?'

  return (
    <>
    <nav className="top-nav">
      <div className="top-nav-left">
        <span className="top-nav-brand" title="Pipesets AI">
          <span className="top-nav-logo" aria-hidden="true">◆</span>Pipesets AI
        </span>

        {/* Workspace / project — the scope everything below works in */}
        <div className="top-nav-context" aria-label="Workspace and project">
          <select className="top-nav-context-select" aria-label="Workspace" value={tenantId} onChange={(e) => onTenantChange(e.target.value)}>
            {tenantOptions.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          <span className="top-nav-context-sep" aria-hidden="true">/</span>
          <select className="top-nav-context-select" aria-label="Project" value={projectId} onChange={(e) => onProjectChange(e.target.value)}>
            {projectOptions.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </div>

        <div className="top-nav-views" role="tablist">
          {VIEW_GROUPS.map((group, gi) => (
            <div key={gi} className="top-nav-view-group">
              {group.map(({ id, label }) => (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={view === id}
                  className={`top-nav-view-btn${view === id ? ' top-nav-view-btn--active' : ''}`}
                  onClick={() => onViewChange(id)}
                >
                  {label}
                </button>
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* Right side — settings + account menu */}
      <div className="top-nav-right">
        <div className="tnav-keys-wrap" ref={helpRef}>
          <button
            type="button"
            className={`tnav-icon-btn tnav-docs-btn${view === 'docs' || helpOpen ? ' tnav-icon-btn--active' : ''}`}
            title="Help — docs, shortcuts, report a bug"
            aria-haspopup="menu"
            aria-expanded={helpOpen}
            onClick={() => setHelpOpen((o) => !o)}
          >
            <CircleHelp size={16} strokeWidth={2} aria-hidden="true" />
            <span>Help</span>
            <ChevronDown size={13} strokeWidth={2} aria-hidden="true" className="tnav-help-caret" />
          </button>

          {helpOpen && (
            <div className="tnav-menu tnav-help-menu" role="menu">
              <button type="button" role="menuitem" className="tnav-menu-item" onClick={helpAction(() => onViewChange('docs'))}>
                <span className="tnav-menu-label"><BookOpen size={15} aria-hidden="true" />Docs</span>
              </button>
              <button type="button" role="menuitem" className="tnav-menu-item" onClick={helpAction(() => setShortcutsOpen(true))}>
                <span className="tnav-menu-label"><Keyboard size={15} aria-hidden="true" />Keyboard shortcuts</span>
                <kbd className="tnav-menu-kbd">?</kbd>
              </button>
              <div className="tnav-menu-sep" />
              <button type="button" role="menuitem" className="tnav-menu-item" onClick={helpAction(() => openIssue('bug', view, commit))}>
                <span className="tnav-menu-label"><Bug size={15} aria-hidden="true" />Report a bug</span>
                <span className="tnav-menu-meta">GitHub ↗</span>
              </button>
              <button type="button" role="menuitem" className="tnav-menu-item" onClick={helpAction(() => openIssue('idea', view, commit))}>
                <span className="tnav-menu-label"><Lightbulb size={15} aria-hidden="true" />Suggest a feature</span>
                <span className="tnav-menu-meta">GitHub ↗</span>
              </button>
              <div className="tnav-menu-sep" />
              <button type="button" role="menuitem" className="tnav-menu-item" onClick={helpAction(() => setAboutOpen(true))}>
                <span className="tnav-menu-label"><Info size={15} aria-hidden="true" />About Pipesets</span>
              </button>
            </div>
          )}
        </div>
        <button
          type="button"
          className={`tnav-icon-btn tnav-whatsnew-btn${whatsNewOpen ? ' tnav-icon-btn--active' : ''}`}
          title={unseenRelease ? "What's new — a new release" : "What's new"}
          aria-label={unseenRelease ? "What's new (new release)" : "What's new"}
          onClick={() => setWhatsNewOpen(true)}
        >
          <Megaphone size={16} strokeWidth={2} aria-hidden="true" />
          {unseenRelease && <span className="tnav-whatsnew-dot" aria-hidden="true" />}
        </button>
        <button
          type="button"
          className={`tnav-icon-btn${view === 'settings' ? ' tnav-icon-btn--active' : ''}`}
          title="Settings"
          aria-label="Settings"
          onClick={() => onOpenSettings('members')}
        >
          <Settings size={17} strokeWidth={2} aria-hidden="true" />
        </button>

        <div className="tnav-keys-wrap" ref={menuRef}>
          <button
            type="button"
            className="tnav-avatar-btn"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            title={user?.email || 'Account'}
            onClick={() => setMenuOpen((o) => !o)}
          >
            <span className="tnav-avatar">{initials}</span>
            {keyCount === 0 && <span className="tnav-avatar-warn" title="No model provider keys set" />}
            <span className="tnav-avatar-caret" aria-hidden="true">▾</span>
          </button>

          {menuOpen && (
            <div className="tnav-menu" role="menu">
              {user && (
                <div className="tnav-menu-profile">
                  <span className="tnav-avatar tnav-avatar--lg">{initials}</span>
                  <div className="tnav-menu-profile-text">
                    <strong>{user.display_name || user.email}</strong>
                    {user.display_name && <span>{user.email}</span>}
                  </div>
                </div>
              )}
              <button type="button" role="menuitem" className="tnav-menu-item" onClick={() => openSettings('providerkeys')}>
                <span>Model provider keys</span>
                <span className={`tnav-menu-meta${keyCount ? '' : ' tnav-menu-meta--warn'}`}>
                  {keyCount ? `${keyCount} set` : 'None set'}
                </span>
              </button>
              <button type="button" role="menuitem" className="tnav-menu-item" onClick={() => openSettings('secrets')}>
                <span>Secrets</span>
                <span className="tnav-menu-meta">{secrets.length ? `${secrets.length} saved` : 'None'}</span>
              </button>
              <button type="button" role="menuitem" className="tnav-menu-item" onClick={() => openSettings('members')}>
                Settings
              </button>
              {user && (
                <>
                  <div className="tnav-menu-sep" />
                  <button type="button" role="menuitem" className="tnav-menu-item" onClick={onLogout}>Sign out</button>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </nav>

    {whatsNewOpen && <WhatsNewPanel onClose={() => setWhatsNewOpen(false)} onSeen={onReleaseSeen} />}
    {aboutOpen && <AboutPanel onClose={() => setAboutOpen(false)} />}
    {shortcutsOpen && <KeyboardShortcutsPanel onClose={() => setShortcutsOpen(false)} />}

    {/* Sub-navigation — its own row, only on Monitor and Automation */}
    {view === 'monitor' && <SubNav label="Monitor" tabs={MONITOR_TABS} active={monitorTab} onChange={onMonitorTabChange} />}
    {view === 'automation' && (
      <SubNav label="Automation" tabs={AUTOMATION_TABS} active={automationTab} onChange={onAutomationTabChange} />
    )}
    </>
  )
}

function SubNav<T extends string>({ label, tabs, active, onChange }: {
  label: string
  tabs: { id: T; label: string }[]
  active: T
  onChange: (t: T) => void
}) {
  return (
    <nav className="top-subnav" aria-label={label}>
      <div className="top-subnav-group">
        {tabs.map(({ id, label: tabLabel }) => (
          <button
            key={id}
            type="button"
            className={`top-nav-ops-tab${active === id ? ' top-nav-ops-tab--active' : ''}`}
            aria-current={active === id ? 'page' : undefined}
            onClick={() => onChange(id)}
          >
            {tabLabel}
          </button>
        ))}
      </div>
    </nav>
  )
}

export type { TopView, MonitorTab, AutomationTab, SettingsTab }
