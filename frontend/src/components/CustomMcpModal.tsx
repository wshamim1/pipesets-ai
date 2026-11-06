import { useEffect, useRef, useState } from 'react'
import { API_BASE } from '../types'
import type { CustomMcpRecord } from '../types'
import { joinArgs, parseMcpConfig, splitArgs } from '../utils/mcpImport'
import { HelpLink } from './docs/HelpLink'

interface Props {
  server?: CustomMcpRecord
  initialDraft?: {
    name?: string
    icon?: string
    description?: string
    transport?: 'stdio' | 'sse' | 'http'
    command?: string
    args?: string[]
    env_vars?: Record<string, string>
    url?: string
    headers?: Record<string, string>
  }
  onSaved: (server: CustomMcpRecord) => void
  onClose: () => void
}

const TRANSPORTS: { value: 'stdio' | 'sse' | 'http'; icon: string; label: string; sub: string }[] = [
  { value: 'stdio', icon: '⌨️', label: 'stdio',  sub: 'CLI command' },
  { value: 'http',  icon: '🌐', label: 'HTTP',   sub: 'Streamable HTTP' },
  { value: 'sse',   icon: '📡', label: 'SSE',    sub: 'Legacy HTTP+SSE' },
]

const PRESETS = [
  { id: 'postgres',   icon: '🐘', label: 'Postgres',     sub: 'PostgreSQL DB', transport: 'stdio' as const, command: 'uvx', args: 'postgres-mcp@0.3.0 --access-mode=restricted', env: '{\n  "DATABASE_URI": "postgresql://localhost/mydb"\n}',  url: '', name: 'PostgreSQL MCP',     desc: 'Query tables and inspect schemas in PostgreSQL (read-only; postgres-mcp by Crystal DBA).' },
  { id: 'filesystem', icon: '📁', label: 'Filesystem',   sub: 'Local files',   transport: 'stdio' as const, command: 'npx', args: '-y @modelcontextprotocol/server-filesystem@2.1.0 /Users/username/Desktop',  env: '{}',  url: '', name: 'Local Filesystem MCP', desc: 'Read, write, and browse directories on the local machine.' },
  { id: 'git',        icon: '🐙', label: 'Git',          sub: 'Repos & diffs', transport: 'stdio' as const, command: 'uvx', args: 'mcp-server-git@2026.10.28 --repository .',                                      env: '{}',  url: '', name: 'Git Operations MCP',  desc: 'Inspect git branches, commits, diffs, and repositories.' },
  { id: 'sqlite',     icon: '💾', label: 'SQLite',       sub: 'Local DB',      transport: 'stdio' as const, command: 'uvx', args: 'mcp-server-sqlite@2025.4.25 --db-path ./data.db',                              env: '{}',  url: '', name: 'SQLite MCP',          desc: 'Connect and execute SQL on local SQLite database files.' },
  { id: 'github',     icon: '🐙', label: 'GitHub',       sub: 'PRs & issues',  transport: 'http' as const, command: '', args: '',                              env: '{}', headers: '{\n  "Authorization": "Bearer <GitHub personal access token>",\n  "X-MCP-Readonly": "true"\n}', url: 'https://api.githubcopilot.com/mcp/', name: 'GitHub MCP', desc: 'Repos, files, issues and pull requests through GitHub\'s own remote server.' },
  { id: 'gitlab',     icon: '🦊', label: 'GitLab',       sub: 'Projects & MRs', transport: 'stdio' as const, command: 'npx', args: '-y @zereight/mcp-gitlab@2.3.19',                              env: '{\n  "GITLAB_PERSONAL_ACCESS_TOKEN": "",\n  "GITLAB_API_URL": "https://gitlab.com/api/v4"\n}', url: '', name: 'GitLab MCP', desc: 'Work with GitLab projects, merge requests, and issues.' },
  { id: 'docker',     icon: '🐳', label: 'Docker',       sub: 'Containers',    transport: 'stdio' as const, command: 'uvx', args: 'mcp-server-docker@0.3.0',                                                       env: '{}',  url: '', name: 'Docker MCP', desc: 'Inspect images, containers, and Docker runtime resources.' },
  { id: 'kubernetes', icon: '☸️', label: 'Kubernetes',   sub: 'Cluster ops',   transport: 'stdio' as const, command: 'npx', args: '-y mcp-server-kubernetes@4.2.1',                                            env: '{\n  "KUBECONFIG": ""\n}', url: '', name: 'Kubernetes MCP', desc: 'Browse namespaces, pods, and workloads in Kubernetes clusters.' },
  { id: 'playwright', icon: '🎭', label: 'Playwright',   sub: 'Browser auto',  transport: 'stdio' as const, command: 'npx', args: '-y @playwright/mcp@0.0.84',                                                   env: '{}',  url: '', name: 'Playwright MCP', desc: 'Automate browser tasks like navigation, clicking, typing, and snapshots.' },
  { id: 'fetch',      icon: '🔎', label: 'Fetch',        sub: 'Read webpages', transport: 'stdio' as const, command: 'uvx', args: 'mcp-server-fetch@2026.10.28',                                                    env: '{}',  url: '', name: 'Fetch MCP', desc: 'Fetch and convert web pages for agent-friendly processing.' },
  { id: 'brave',      icon: '🦁', label: 'Brave Search', sub: 'Web search',    transport: 'stdio' as const, command: 'npx', args: '-y @brave/brave-search-mcp-server@2.1.4',                        env: '{\n  "BRAVE_API_KEY": ""\n}', url: '', name: 'Brave Search MCP', desc: 'Web, local and news search through Brave Search (Brave\'s own server).' },
  { id: 'firecrawl',  icon: '🔥', label: 'Firecrawl',    sub: 'Crawl & scrape', transport: 'stdio' as const, command: 'npx', args: '-y firecrawl-mcp@3.36.0',                                                   env: '{\n  "FIRECRAWL_API_KEY": ""\n}', url: '', name: 'Firecrawl MCP', desc: 'Crawl and extract structured content from websites.' },
  { id: 'notion',     icon: '📓', label: 'Notion',       sub: 'Docs & DBs',    transport: 'stdio' as const, command: 'npx', args: '-y @notionhq/notion-mcp-server@2.6.1',                                     env: '{\n  "NOTION_TOKEN": ""\n}', url: '', name: 'Notion MCP', desc: 'Search and edit Notion pages and databases.' },
  { id: 'linear',     icon: '📐', label: 'Linear',       sub: 'Issue tracker', transport: 'http' as const, command: '', args: '',                                                      env: '{}', headers: '{\n  "Authorization": "Bearer <Linear API key>"\n}', url: 'https://mcp.linear.app/mcp', name: 'Linear MCP', desc: 'Linear issues, projects and cycles through Linear\'s own remote server.' },
  { id: 'jira',       icon: '🧩', label: 'Jira',         sub: 'Atlassian',     transport: 'stdio' as const, command: 'uvx', args: 'mcp-atlassian@0.23.1',                                        env: '{\n  "JIRA_URL": "",\n  "JIRA_USERNAME": "",\n  "JIRA_API_TOKEN": ""\n}', url: '', name: 'Jira MCP', desc: 'Operate Jira issues, projects, and sprints through Atlassian MCP.' },
  { id: 'remote',     icon: '🌐', label: 'Remote',       sub: 'Remote server', transport: 'http'  as const, command: '',    args: '',                                                                   env: '{}',  url: 'https://example.com/mcp', name: 'Remote MCP', desc: 'Connect to a remote MCP endpoint over Streamable HTTP (legacy SSE endpoints are detected automatically).' },
]

export function CustomMcpModal({ server, initialDraft, onSaved, onClose }: Props) {
  const isEdit = !!server

  const [name, setName] = useState(server?.name ?? initialDraft?.name ?? '')
  const [icon, setIcon] = useState(server?.icon ?? initialDraft?.icon ?? '🔌')
  const [description, setDescription] = useState(server?.description ?? initialDraft?.description ?? '')
  const [transport, setTransport] = useState<'stdio' | 'sse' | 'http'>(server?.transport ?? initialDraft?.transport ?? 'stdio')
  const [activePreset, setActivePreset] = useState('')

  // stdio fields
  const [command, setCommand] = useState(server?.command ?? initialDraft?.command ?? 'npx')
  const [argsStr, setArgsStr] = useState(
    server?.args ? joinArgs(server.args)
    : (initialDraft?.args ? joinArgs(initialDraft.args) : '-y @modelcontextprotocol/server-postgres postgresql://localhost/mydb')
  )
  const [envJson, setEnvJson] = useState(
    server?.env_vars ? JSON.stringify(server.env_vars, null, 2)
    : JSON.stringify(initialDraft?.env_vars ?? {}, null, 2)
  )

  // sse/http fields
  const [url, setUrl] = useState(server?.url ?? initialDraft?.url ?? 'http://localhost:3000/sse')
  const [headersJson, setHeadersJson] = useState(
    server?.headers ? JSON.stringify(server.headers, null, 2)
    : JSON.stringify(initialDraft?.headers ?? {}, null, 2)
  )

  const [isTesting, setIsTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string; tools?: any[] } | null>(null)
  const [isSaving, setIsSaving] = useState(false)
  const [errorMsg, setErrorMsg] = useState('')

  // Paste a config copied from a server's README (mcpServers / servers JSON)
  const [importOpen, setImportOpen] = useState(false)
  const [importText, setImportText] = useState('')
  const [importNote, setImportNote] = useState<{ ok: boolean; text: string } | null>(null)

  // OAuth (remote servers, once saved)
  const [oauthStatus, setOauthStatus] = useState(server?.oauth_status ?? 'none')
  const [oauthBusy, setOauthBusy] = useState(false)
  const [oauthMsg, setOauthMsg] = useState('')
  const [ownClient, setOwnClient] = useState(false)
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')
  const oauthCancel = useRef(false)
  useEffect(() => () => { oauthCancel.current = true }, [])

  // The callback page can't message this window (COOP), so poll the server's status instead
  const waitForSignIn = async (id: string): Promise<boolean> => {
    const deadline = Date.now() + 5 * 60_000
    while (!oauthCancel.current && Date.now() < deadline) {
      await new Promise(r => setTimeout(r, 1500))
      const res = await fetch(`${API_BASE}/api/custom-mcp`)
      if (!res.ok) continue
      const rec = (await res.json() as CustomMcpRecord[]).find(r => r.id === id)
      if (rec?.oauth_status === 'connected') return true
    }
    return false
  }

  const handleConnectOAuth = async () => {
    if (!server) return
    setOauthBusy(true)
    setOauthMsg('')
    oauthCancel.current = false
    try {
      const res = await fetch(`${API_BASE}/api/custom-mcp/${server.id}/oauth/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(ownClient ? { client_id: clientId.trim(), client_secret: clientSecret.trim() } : {}),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Could not start sign-in')
      if (!window.open(data.authorization_url, 'mcp-oauth', 'popup,width=520,height=720')) {
        throw new Error('Allow pop-ups for this site to sign in.')
      }
      setOauthMsg('Finish signing in in the new window…')
      if (!(await waitForSignIn(server.id))) {
        if (!oauthCancel.current) setOauthMsg('Sign-in wasn\'t completed. Try again.')
        return
      }
      setOauthStatus('connected')
      const disc = await fetch(`${API_BASE}/api/custom-mcp/${server.id}/discover`, { method: 'POST' }).then(r => r.json())
      setTestResult(disc.success
        ? { success: true, message: `Connected! Discovered ${disc.tool_count} tool(s).`, tools: disc.tools }
        : { success: false, message: `Signed in, but listing tools failed: ${disc.error}` })
      setOauthMsg('')
    } catch (err: any) {
      setOauthMsg(err.message || 'Sign-in failed')
    } finally {
      setOauthBusy(false)
    }
  }

  const handleDisconnectOAuth = async () => {
    if (!server) return
    oauthCancel.current = true
    await fetch(`${API_BASE}/api/custom-mcp/${server.id}/oauth`, { method: 'DELETE' })
    setOauthStatus('none')
    setOauthMsg('')
  }

  const applyPreset = (presetId: string) => {
    const p = PRESETS.find(x => x.id === presetId)
    if (!p) return
    setActivePreset(presetId)
    setName(p.name)
    setIcon(p.icon)
    setDescription(p.desc)
    setTransport(p.transport)
    setCommand(p.command)
    setArgsStr(p.args)
    setEnvJson(p.env)
    if (p.url) setUrl(p.url)
    setHeadersJson('headers' in p && p.headers ? p.headers : '{}')
    setTestResult(null)
  }

  const applyImport = () => {
    try {
      const { server: s, others, ignored } = parseMcpConfig(importText)
      if (s.name) setName(s.name)
      setTransport(s.transport)
      setCommand(s.command)
      setArgsStr(joinArgs(s.args))
      setEnvJson(JSON.stringify(s.env_vars, null, 2))
      setHeadersJson(JSON.stringify(s.headers, null, 2))
      if (s.url) setUrl(s.url)
      setActivePreset('')
      setTestResult(null)
      setErrorMsg('')
      const notes = [`Filled in${s.name ? ` "${s.name}"` : ''} — check the fields, then Test connection.`]
      if (others.length) notes.push(`Also in the paste: ${others.join(', ')}. Add them one at a time.`)
      if (ignored.length) notes.push(`Not used: ${ignored.join(', ')}.`)
      setImportNote({ ok: true, text: notes.join(' ') })
      setImportOpen(false)
    } catch (e: any) {
      setImportNote({ ok: false, text: e.message })
    }
  }

  const handleTransportClick = (t: 'stdio' | 'sse' | 'http') => {
    setTransport(t)
    setActivePreset('')
    setTestResult(null)
  }

  const handleTestConnection = async () => {
    setIsTesting(true)
    setTestResult(null)
    setErrorMsg('')
    let parsedArgs: string[] = []
    let parsedEnv: Record<string, string> = {}
    let parsedHeaders: Record<string, string> = {}
    try {
      parsedArgs = splitArgs(argsStr)
      parsedEnv = JSON.parse(envJson || '{}')
      parsedHeaders = JSON.parse(headersJson || '{}')
    } catch (e: any) {
      setErrorMsg(`JSON Parse Error: ${e.message}`)
      setIsTesting(false)
      return
    }
    try {
      const res = await fetch(`${API_BASE}/api/custom-mcp/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transport, command, args: parsedArgs, env_vars: parsedEnv, url, headers: parsedHeaders }),
      })
      const data = await res.json()
      setTestResult(data.success
        ? { success: true, message: `Connected! Discovered ${data.tool_count} tool(s).`, tools: data.tools }
        : data.auth_required
          ? { success: false, message: isEdit
              ? 'This server needs sign-in. Use "Connect with OAuth" below, or add an Authorization header.'
              : 'This server needs sign-in. Add it, then edit it and choose "Connect with OAuth" — or add an Authorization header.' }
          : { success: false, message: `Handshake failed: ${data.error}` }
      )
    } catch (err: any) {
      setTestResult({ success: false, message: `Network error: ${err.message}` })
    } finally {
      setIsTesting(false)
    }
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) { setErrorMsg('Server name is required.'); return }
    setIsSaving(true)
    setErrorMsg('')
    let parsedArgs: string[] = []
    let parsedEnv: Record<string, string> = {}
    let parsedHeaders: Record<string, string> = {}
    try {
      parsedArgs = splitArgs(argsStr)
      parsedEnv = JSON.parse(envJson || '{}')
      parsedHeaders = JSON.parse(headersJson || '{}')
    } catch (e: any) {
      setErrorMsg(`JSON Parse Error: ${e.message}`)
      setIsSaving(false)
      return
    }
    const payload = {
      name: name.trim(), icon: icon.trim() || '🔌', description: description.trim(),
      transport, command: command.trim(), args: parsedArgs, env_vars: parsedEnv,
      url: url.trim(), headers: parsedHeaders,
      tools_cache: testResult?.tools ?? server?.tools_cache ?? [],
    }
    try {
      let res: Response
      if (isEdit && server) {
        res = await fetch(`${API_BASE}/api/custom-mcp/${server.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      } else {
        res = await fetch(`${API_BASE}/api/custom-mcp`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      }
      if (!res.ok) { const err = await res.json(); throw new Error(err.detail || 'Failed to save MCP server') }
      const saved: CustomMcpRecord = await res.json()
      onSaved(saved)
      onClose()
    } catch (err: any) {
      setErrorMsg(err.message || 'Error saving custom MCP server')
    } finally {
      setIsSaving(false)
    }
  }

  const currentTransport = TRANSPORTS.find(t => t.value === transport)!

  return (
    <div className="modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="conn-modal-shell">

        {/* ── Header ── */}
        <div className="conn-modal-header">
          <div className="conn-modal-heading">
            <span className="conn-modal-icon">{icon}</span>
            <div>
              <h3 className="conn-modal-title">
                {isEdit ? `Edit MCP: ${server!.name}` : 'Add Custom MCP Server'}
                <HelpLink page="04-mcp" section="add-your-own-mcp-server" label="Adding an MCP server" />
              </h3>
              <p className="conn-modal-subtitle">
                {currentTransport.label} transport · {currentTransport.sub}
              </p>
            </div>
          </div>
          <button type="button" className="modal-close-btn" onClick={onClose}>✕</button>
        </div>

        {/* ── Two-column body ── */}
        <div className="conn-modal-body">

          {/* LEFT — transport + presets nav */}
          <nav className="conn-provider-nav">
            <p className="conn-nav-label">Transport</p>
            {TRANSPORTS.map(t => (
              <button
                key={t.value}
                type="button"
                className={`conn-nav-item ${transport === t.value ? 'active' : ''}`}
                onClick={() => handleTransportClick(t.value)}
              >
                <span className="conn-nav-icon">{t.icon}</span>
                <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                  <span className="conn-nav-name">{t.label}</span>
                  <span className="conn-nav-sub">{t.sub}</span>
                </div>
              </button>
            ))}

            <div className="conn-nav-divider" />
            <p className="conn-nav-label">Templates</p>
            {PRESETS.map(p => (
              <button
                key={p.id}
                type="button"
                className={`conn-nav-item ${activePreset === p.id ? 'active' : ''}`}
                onClick={() => applyPreset(p.id)}
              >
                <span className="conn-nav-icon">{p.icon}</span>
                <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                  <span className="conn-nav-name">{p.label}</span>
                  <span className="conn-nav-sub">{p.sub}</span>
                </div>
              </button>
            ))}
          </nav>

          {/* RIGHT — config form */}
          <form className="conn-config-panel" onSubmit={handleSave}>
            <div className="conn-config-scroll">

              {errorMsg && <div className="ct-save-error conn-error">{errorMsg}</div>}

              {/* Paste a config */}
              <div className="mcp-test-header" style={{ marginBottom: 10 }}>
                <button type="button" className="mcp-test-btn" onClick={() => { setImportOpen(!importOpen); setImportNote(null) }}>
                  {importOpen ? 'Close' : 'Paste JSON config'}
                </button>
                <span className="field-hint">The "mcpServers" block from a server's README, Claude Desktop or Cursor</span>
              </div>
              {importOpen && (
                <div className="form-group">
                  <textarea rows={8} className="field-textarea font-mono" style={{ fontSize: 11 }} autoFocus
                    placeholder={'{\n  "mcpServers": {\n    "my-server": { "command": "uvx", "args": ["my-mcp-server"] }\n  }\n}'}
                    value={importText} onChange={(e) => setImportText(e.target.value)} />
                  <div className="mcp-test-header" style={{ marginTop: 6 }}>
                    <button type="button" className="mcp-test-btn" onClick={applyImport} disabled={!importText.trim()}>Fill in the form</button>
                  </div>
                </div>
              )}
              {importNote && (
                <div className={`mcp-test-banner ${importNote.ok ? 'success' : 'error'}`} style={{ marginBottom: 10 }}>{importNote.text}</div>
              )}

              {/* Identity */}
              <div className="conn-section-label">Identity</div>
              <div className="form-row" style={{ gap: 10, marginBottom: 10 }}>
                <div className="form-group" style={{ flex: '0 0 56px' }}>
                  <label className="field-label">Icon</label>
                  <input type="text" className="field-input ct-icon-input" value={icon} onChange={(e) => setIcon(e.target.value)} maxLength={4} />
                </div>
                <div className="form-group flex-1">
                  <label className="field-label">Server Name *</label>
                  <input type="text" className="field-input" placeholder="e.g. Postgres DB MCP, Local Filesystem..." value={name} onChange={(e) => setName(e.target.value)} required />
                </div>
              </div>
              <div className="form-group">
                <label className="field-label">Description</label>
                <input type="text" className="field-input" placeholder="What tools or resources does this server provide?" value={description} onChange={(e) => setDescription(e.target.value)} />
              </div>

              {/* Transport-specific fields */}
              {transport === 'stdio' ? (
                <>
                  <div className="conn-section-label">Command</div>
                  <div className="form-row" style={{ gap: 10 }}>
                    <div className="form-group" style={{ width: 110 }}>
                      <label className="field-label">Executable *</label>
                      <input type="text" className="field-input font-mono" placeholder="npx, uvx, python" value={command} onChange={(e) => setCommand(e.target.value)} required />
                    </div>
                    <div className="form-group flex-1">
                      <label className="field-label">Arguments</label>
                      <input type="text" className="field-input font-mono" placeholder="-y some-mcp-server@1.2.3 --flag" value={argsStr} onChange={(e) => setArgsStr(e.target.value)} />
                    </div>
                  </div>
                  <div className="conn-section-label">Environment Variables</div>
                  <div className="form-group">
                    <label className="field-label">JSON <span className="field-hint">— tokens, API keys, credentials</span></label>
                    <textarea rows={4} className="field-textarea font-mono" style={{ fontSize: 11 }}
                      placeholder='{ "DB_PASSWORD": "secret", "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_..." }'
                      value={envJson} onChange={(e) => setEnvJson(e.target.value)} />
                  </div>
                </>
              ) : (
                <>
                  <div className="conn-section-label">Endpoint</div>
                  <div className="form-group">
                    <label className="field-label">Server URL *</label>
                    <input type="url" className="field-input font-mono" placeholder="http://localhost:8000/sse or https://api.example.com/mcp" value={url} onChange={(e) => setUrl(e.target.value)} required />
                  </div>
                  <div className="conn-section-label">Headers (JSON)</div>
                  <div className="form-group">
                    <textarea rows={4} className="field-textarea font-mono" style={{ fontSize: 11 }}
                      placeholder='{ "Authorization": "Bearer sk-..." }'
                      value={headersJson} onChange={(e) => setHeadersJson(e.target.value)} />
                  </div>
                  <div className="conn-section-label">OAuth</div>
                  {!isEdit ? (
                    <p className="field-hint">For servers that need sign-in (GitHub, Linear, Notion, …): add the server, then edit it to connect.</p>
                  ) : (
                    <div className="form-group">
                      <div className="mcp-test-header">
                        {oauthStatus === 'connected' ? (
                          <>
                            <span className="field-hint">✅ Connected</span>
                            <button type="button" className="mcp-test-btn" onClick={handleConnectOAuth} disabled={oauthBusy}>Reconnect</button>
                            <button type="button" className="cancel-btn" onClick={handleDisconnectOAuth}>Disconnect</button>
                          </>
                        ) : (
                          <>
                            <button type="button" className="mcp-test-btn" onClick={handleConnectOAuth} disabled={oauthBusy}>
                              {oauthBusy ? 'Waiting for sign-in…' : 'Connect with OAuth'}
                            </button>
                            {oauthStatus === 'expired' && <span className="field-hint">Sign-in expired</span>}
                            {oauthBusy && <button type="button" className="cancel-btn" onClick={() => { oauthCancel.current = true }}>Cancel</button>}
                          </>
                        )}
                      </div>
                      {oauthMsg && <div className="field-hint" style={{ marginTop: 6 }}>{oauthMsg}</div>}
                      <label className="field-label" style={{ marginTop: 8 }}>
                        <input type="checkbox" checked={ownClient} onChange={(e) => setOwnClient(e.target.checked)} />{' '}
                        Use my own OAuth app <span className="field-hint">— for providers without automatic registration (e.g. GitHub)</span>
                      </label>
                      {ownClient && (
                        <div className="form-row" style={{ gap: 10 }}>
                          <input type="text" className="field-input font-mono" placeholder="Client ID" value={clientId} onChange={(e) => setClientId(e.target.value)} />
                          <input type="password" className="field-input font-mono" placeholder="Client secret (optional)" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} />
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}

              {/* Test section */}
              <div className="mcp-test-section">
                <div className="mcp-test-header">
                  <button type="button" className="mcp-test-btn" onClick={handleTestConnection} disabled={isTesting}>
                    {isTesting ? 'Discovering tools…' : 'Test connection'}
                  </button>
                  <span className="field-hint">Runs initialize &amp; tools/list</span>
                </div>
                {testResult && (
                  <div className={`mcp-test-banner ${testResult.success ? 'success' : 'error'}`} style={{ marginTop: 8 }}>
                    <div>{testResult.message}</div>
                    {testResult.tools && testResult.tools.length > 0 && (
                      <div className="mcp-discovered-list">
                        {testResult.tools.map((t: any, idx: number) => (
                          <div key={idx} className="mcp-tool-pill">
                            <strong>{t.name}</strong>
                            {t.description && <span>: {t.description.slice(0, 60)}</span>}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>

            </div>{/* /conn-config-scroll */}

            <div className="conn-modal-footer">
              <button type="button" className="cancel-btn" onClick={onClose} disabled={isSaving}>Cancel</button>
              <button type="submit" className="save-btn" disabled={isSaving}>
                {isSaving ? 'Saving...' : isEdit ? 'Update MCP Server' : 'Add MCP Server'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}
