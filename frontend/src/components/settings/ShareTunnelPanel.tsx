import { useCallback, useEffect, useState } from 'react'
import { API_BASE } from '../../types'

export interface TunnelStatus {
  enabled: boolean
  installed: boolean
  port: string
  running: boolean
  ours: boolean
  domain: string | null
  public_url: string | null
  inspect_url: string | null
}

const DOMAIN_KEY = 'pipesets.ngrokDomain'

function readDomain(): string {
  try {
    return localStorage.getItem(DOMAIN_KEY) ?? ''
  } catch {
    return ''
  }
}

function saveDomain(domain: string) {
  try {
    localStorage.setItem(DOMAIN_KEY, domain)
  } catch { /* storage blocked: the field just starts empty next time */ }
}

async function call(path: string, init?: RequestInit): Promise<TunnelStatus> {
  const res = await fetch(`${API_BASE}/api/dev/tunnel${path}`, init)
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `HTTP ${res.status}`)
  return body as TunnelStatus
}

/**
 * Settings → Share via ngrok: start an ngrok tunnel to the dev UI and copy its public URL (e.g. to
 * open it on a phone). With a static domain the URL stays the same every time. Dev only.
 */
export function ShareTunnelPanel() {
  const [status, setStatus] = useState<TunnelStatus | null>(null)
  const [domain, setDomain] = useState(readDomain)
  const [busy, setBusy] = useState<'start' | 'stop' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const refresh = useCallback(() => {
    // Leaves any error shown: a refresh after a failed start must not hide why it failed
    call('').then(setStatus).catch((e: Error) => setError(e.message))
  }, [])
  useEffect(refresh, [refresh])

  const act = async (what: 'start' | 'stop') => {
    setBusy(what)
    setError(null)
    try {
      if (what === 'start') saveDomain(domain.trim())
      setStatus(await call(`/${what}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: what === 'start' ? JSON.stringify({ domain: domain.trim() || null }) : undefined,
      }))
    } catch (e) {
      setError((e as Error).message)
      refresh()
    } finally {
      setBusy(null)
    }
  }

  const copy = async (url: string) => {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      setError('Copying was blocked by the browser; select the address and copy it instead.')
    }
  }

  if (!status) {
    return error ? <div className="apikeys-error" role="alert">{error}</div> : <p className="apikeys-intro">Loading…</p>
  }

  return (
    <div className="tunnel-panel">
      <p className="apikeys-intro">
        Opens this development server to the internet through <a href="https://ngrok.com" target="_blank" rel="noreferrer">ngrok</a>,
        so you can try the UI on a phone or show it to someone. Anyone with the address reaches the sign-in page,
        so stop the tunnel when you're done. It also stops when the backend does.
      </p>

      {!status.enabled && (
        <div className="apikeys-error">
          Tunnels are off on this server. They're for development only: start it with <code>./start.sh</code>, or set{' '}
          <code>PIPESETS_DEV_TUNNEL=1</code> for the backend.
        </div>
      )}
      {status.enabled && !status.installed && (
        <div className="apikeys-error">
          ngrok isn't installed on this machine. Install it (<code>brew install ngrok</code>), add your token with{' '}
          <code>ngrok config add-authtoken &lt;token&gt;</code>, then come back.
        </div>
      )}

      {status.running && status.public_url && (
        <section className="cost-card tunnel-live">
          <div className="cost-card-title">
            <span className="tunnel-dot" aria-hidden="true" /> Live{status.ours ? '' : ' · started from a terminal'}
          </div>
          <div className="tunnel-url">
            <a href={status.public_url} target="_blank" rel="noreferrer" className="mono">{status.public_url}</a>
          </div>
          <div className="tunnel-actions">
            <button type="button" className="ops-refresh-btn" onClick={() => void copy(status.public_url!)}>
              {copied ? 'Copied' : 'Copy address'}
            </button>
            {status.inspect_url && (
              <a className="ops-refresh-btn" href={status.inspect_url} target="_blank" rel="noreferrer">Inspect traffic</a>
            )}
            {status.ours && (
              <button type="button" className="ops-refresh-btn tunnel-stop" onClick={() => void act('stop')} disabled={busy !== null}>
                {busy === 'stop' ? 'Stopping…' : 'Stop tunnel'}
              </button>
            )}
          </div>
          {!status.ours && (
            <p className="apikeys-hint">This tunnel was started outside Pipesets, so stop it where it runs (Ctrl+C in that terminal).</p>
          )}
        </section>
      )}

      {status.enabled && status.installed && !status.running && (
        <section className="cost-card">
          <div className="cost-card-title">Start a tunnel to port {status.port}</div>
          <label className="dbsetup-field tunnel-domain">Static domain (optional)
            <input className="ops-select" value={domain} onChange={(e) => setDomain(e.target.value)}
              placeholder="your-name.ngrok-free.app" autoComplete="off" spellCheck={false} />
          </label>
          <p className="apikeys-hint">
            Without one, ngrok picks a new random address each time. Every free ngrok account has one static domain:
            find it in the <a href="https://dashboard.ngrok.com/domains" target="_blank" rel="noreferrer">ngrok dashboard → Domains</a>,
            and the address will stay the same on every start.
          </p>
          <button type="button" className="ops-refresh-btn dbsetup-apply" onClick={() => void act('start')} disabled={busy !== null}>
            {busy === 'start' ? 'Starting…' : 'Start tunnel'}
          </button>
        </section>
      )}

      {error && <pre className="apikeys-error tunnel-error" role="alert">{error}</pre>}
    </div>
  )
}
