import { useState } from 'react'
import { refreshAgentCatalog, resetAgentPackages, setAgentsInstalled, useAgentCatalog } from '../../utils/agentCatalog'
import type { BuiltinAgent } from '../../utils/agentCatalog'

type Show = 'all' | 'installed' | 'available'

const SOURCE_LABEL: Record<string, string> = {
  default: 'Default',
  in_use: 'Used in a pipeline',
}

type Need = BuiltinAgent['tools'][number]
const toolName = (n: Need, id: string) => n.names?.[id] ?? id

/** One tool need as a line: the tool that meets it, or the options when none is installed yet. */
function NeedLine({ need }: { need: Need }) {
  const met = !!need.installed
  const mark = met ? '✓' : need.optional ? '○' : '⚠'
  const what = met
    ? toolName(need, need.installed!)
    : need.ids.length > 1 ? `Any of: ${need.ids.map((i) => toolName(need, i)).join(', ')}` : toolName(need, need.ids[0])
  return (
    <li className={`pkg-need${met ? ' pkg-need--met' : need.optional ? ' pkg-need--optional' : ' pkg-need--missing'}`}
      title={need.ids.map((i) => toolName(need, i)).join(' / ')}>
      <span className="pkg-need-mark" aria-hidden="true">{mark}</span>
      <span>
        <span className="pkg-need-what">{what}</span>
        {need.why && <span className="pkg-need-why"> — {need.why}</span>}
        {need.optional && <span className="pkg-need-why"> (optional)</span>}
      </span>
    </li>
  )
}

/** Settings → Agents: install built-in agents to offer them in the builder's sidebar, with the tools they need. */
export function AgentPackagesPanel({ onToolsChanged }: { onToolsChanged?: () => void }) {
  const catalog = useAgentCatalog()
  const [show, setShow] = useState<Show>('all')
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  // Groups the user folded; all start open
  const [closed, setClosed] = useState<Set<string>>(() => new Set())
  const toggleGroup = (name: string) => setClosed((prev) => {
    const next = new Set(prev)
    if (next.has(name)) next.delete(name)
    else next.add(name)
    return next
  })

  const q = query.trim().toLowerCase()
  const shown = catalog.agents.filter((a) => (show === 'all' || (show === 'installed') === a.installed)
    && (!q || [a.name, a.description, a.role, a.group].some((f) => f.toLowerCase().includes(q))))
  const groups = catalog.groups
    .map((name) => ({ name, items: shown.filter((a) => a.group === name) }))
    .filter((g) => g.items.length > 0)

  const change = async (agent: BuiltinAgent, installed: boolean, withTools = false) => {
    setBusy(agent.id)
    setError('')
    setNotice('')
    try {
      const r = await setAgentsInstalled([agent.id], installed, withTools)
      if (r.tools_installed.length > 0) {
        setNotice(`Installed ${agent.name} and its tools: ${r.tools_installed.join(', ')}.`)
        onToolsChanged?.()
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  const resetAll = async () => {
    if (!window.confirm('Forget every agent install and uninstall in this workspace? The starter roles, plus agents your pipelines use, will be installed again.')) return
    setBusy('__reset__')
    setError('')
    try {
      await resetAgentPackages()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  if (catalog.groups.length === 0) {
    return (
      <div className="settings-card">
        <p className="settings-card-hint">Loading… <button type="button" className="ops-link-btn" onClick={() => refreshAgentCatalog()}>Retry</button></p>
      </div>
    )
  }

  return (
    <div className="settings-card">
      <div className="settings-card-header">
        <p className="settings-card-hint">
          Installed agents appear in the builder's sidebar under Agents; the rest wait here. Agents that work with tools
          list the tools they need — install them together, or attach your own after dropping the agent.
          Uninstalling only hides an agent from the sidebar; pipelines that use it keep working.
          {!catalog.can_edit && ' You can browse agents; installing them needs write access to agents.'}
        </p>
        {catalog.can_edit && (
          <span className="pkg-summary-actions">
            <button type="button" className="ops-link-btn" onClick={resetAll} disabled={busy !== null}>Reset to defaults</button>
          </span>
        )}
      </div>

      <div className="pkg-toolbar">
        <div className="backends-scope" role="group" aria-label="Show">
          {(['all', 'installed', 'available'] as Show[]).map((s) => (
            <button key={s} type="button"
              className={`backends-scope-btn${show === s ? ' backends-scope-btn--active' : ''}`}
              aria-pressed={show === s} onClick={() => setShow(s)}>
              {s === 'all' ? 'All' : s === 'installed' ? 'Installed' : 'Not installed'}
            </button>
          ))}
        </div>
        <input type="search" className="settings-key-input pkg-search" placeholder="Search agents…"
          aria-label="Search agents" value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>

      <div className="pkg-summary">
        <span>{catalog.agents.filter((a) => a.installed).length} of {catalog.agents.length} agents installed</span>
      </div>
      {error && <div className="backends-error">{error}</div>}
      {notice && <div className="pkg-reload-result" role="status">{notice}</div>}
      {groups.length === 0 && <p className="settings-card-hint">No agents match.</p>}

      {groups.map((g) => (
        <section key={g.name} className="pkg-group" aria-label={g.name}>
          <h3 className="pkg-group-title">
            <button type="button" className="pkg-group-toggle" aria-expanded={!closed.has(g.name) || q !== ''}
              disabled={q !== ''} onClick={() => toggleGroup(g.name)}>
              <span className="pkg-group-chevron" aria-hidden="true">{!closed.has(g.name) || q !== '' ? '▾' : '▸'}</span>
              {g.name}
              <span className="pkg-group-count">{g.items.filter((a) => a.installed).length} / {g.items.length} installed</span>
            </button>
          </h3>
          {(!closed.has(g.name) || q !== '') && (
          <div className="pkg-grid">
            {g.items.map((a) => (
              <div key={a.id} className={`pkg-card${a.installed ? ' pkg-card--installed' : ''}`}>
                <div className="pkg-card-head">
                  <span className="pkg-icon" aria-hidden="true">{a.icon}</span>
                  <span className="pkg-name">{a.name}</span>
                  {a.is_new && <span className="tool-icon-new">New</span>}
                </div>
                <p className="pkg-desc">{a.description}</p>
                {a.tools.length > 0 && (
                  <ul className="pkg-needs" aria-label={`Tools ${a.name} needs`}>
                    {a.tools.map((n) => <NeedLine key={n.ids.join('|')} need={n} />)}
                  </ul>
                )}
                <div className="pkg-card-foot pkg-card-foot--wrap">
                  <span className="pkg-badges">
                    {a.installed && a.source && SOURCE_LABEL[a.source] && <span className="pkg-badge">{SOURCE_LABEL[a.source]}</span>}
                    {a.in_use && a.source !== 'in_use' && <span className="pkg-badge">Used in a pipeline</span>}
                    {a.eval_cases > 0 && <span className="pkg-badge" title="Copy it into an eval dataset from the agent's config panel">{a.eval_cases} eval cases</span>}
                    {!a.ready && <span className="pkg-badge">Needs {a.missing_tools.length} tool{a.missing_tools.length === 1 ? '' : 's'}</span>}
                  </span>
                  {catalog.can_edit ? (
                    <span className="pkg-card-actions">
                      {!a.installed && !a.ready && catalog.can_install_tools && (
                        <button type="button" disabled={busy !== null} className="ops-refresh-btn pkg-install"
                          aria-label={`Install ${a.name} with its tools`} onClick={() => change(a, true, true)}>
                          {busy === a.id ? '…' : `Install + ${a.missing_tools.length} tool${a.missing_tools.length === 1 ? '' : 's'}`}
                        </button>
                      )}
                      {a.installed && !a.ready && catalog.can_install_tools && (
                        <button type="button" disabled={busy !== null} className="ops-refresh-btn pkg-install"
                          aria-label={`Install the tools ${a.name} needs`} onClick={() => change(a, true, true)}>
                          {busy === a.id ? '…' : 'Install its tools'}
                        </button>
                      )}
                      <button type="button" disabled={busy !== null}
                        className={a.installed ? 'ops-link-btn pkg-uninstall' : 'ops-refresh-btn pkg-install'}
                        aria-label={`${a.installed ? 'Uninstall' : 'Install'} ${a.name}`}
                        onClick={() => change(a, !a.installed)}>
                        {busy === a.id ? '…' : a.installed ? 'Uninstall' : 'Install'}
                      </button>
                    </span>
                  ) : (
                    <span className="pkg-badge">{a.installed ? 'Installed' : 'Not installed'}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
          )}
        </section>
      ))}
    </div>
  )
}
