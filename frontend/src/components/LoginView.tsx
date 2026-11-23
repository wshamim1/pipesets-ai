import { useEffect, useState, type FormEvent } from 'react'
import { API_BASE } from '../types'
import { useAuth } from '../context/AuthContext'
import '../styles/auth.css'

type Mode = 'login' | 'signup' | 'sso'
type SsoProvider = { id: string; name: string; protocol: 'oidc' | 'saml'; workspace: string }

/** Leave for the identity provider; it sends the browser back here with a one-time code. */
function startSso(providerId: string) {
  const returnTo = encodeURIComponent(window.location.origin)
  window.location.assign(`${API_BASE}/api/auth/sso/${encodeURIComponent(providerId)}/start?return_to=${returnTo}`)
}

export function LoginView() {
  const { login, signup, ssoError } = useAuth()
  const [mode, setMode] = useState<Mode>('login')
  const [signupEnabled, setSignupEnabled] = useState(true)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [workspaceName, setWorkspaceName] = useState('')
  const [error, setError] = useState(ssoError)
  const [ssoChoices, setSsoChoices] = useState<SsoProvider[]>([])
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    fetch(`${API_BASE}/api/auth/config`)
      .then((r) => (r.ok ? r.json() : null))
      .then((cfg) => {
        if (cfg && cfg.signup_enabled === false) {
          setSignupEnabled(false)
          setMode('login')
        }
      })
      .catch(() => setError('Cannot reach the backend. Is it running?'))
  }, [])

  const switchMode = (next: Mode) => {
    setMode(next)
    setError('')
    setSsoChoices([])
  }

  const findSso = async () => {
    const res = await fetch(`${API_BASE}/api/auth/sso/discover?email=${encodeURIComponent(email.trim())}`)
    const providers: SsoProvider[] = res.ok ? (await res.json()).providers ?? [] : []
    if (providers.length === 1) {
      startSso(providers[0].id)
      return
    }
    if (providers.length === 0) {
      const domain = email.trim().split('@')[1] ?? 'this email'
      throw new Error(`Single sign-on isn't set up for ${domain}. Sign in with your password, or ask your administrator.`)
    }
    setSsoChoices(providers)
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      if (mode === 'sso') {
        await findSso()
      } else if (mode === 'login') {
        await login(email.trim(), password)
      } else {
        await signup({
          email: email.trim(),
          password,
          display_name: displayName.trim(),
          workspace_name: workspaceName.trim() || undefined,
        })
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-page">
      <form className="auth-card" onSubmit={submit}>
        <div className="auth-brand">Pipesets AI</div>
        <h1 className="auth-title">
          {mode === 'signup' ? 'Create your account' : mode === 'sso' ? 'Sign in with SSO' : 'Sign in'}
        </h1>
        <p className="auth-subtitle">
          {mode === 'login'
            ? 'Use the email and password for your account.'
            : mode === 'sso'
              ? "Enter your work email. We'll send you to your organization's sign-in page."
              : 'You get your own workspace. Teammates can add you to theirs by email.'}
        </p>

        {signupEnabled && mode !== 'sso' && (
          <div className="auth-tabs" role="tablist">
            <button type="button" role="tab" aria-selected={mode === 'login'}
              className={`auth-tab ${mode === 'login' ? 'auth-tab--active' : ''}`} onClick={() => switchMode('login')}>
              Sign in
            </button>
            <button type="button" role="tab" aria-selected={mode === 'signup'}
              className={`auth-tab ${mode === 'signup' ? 'auth-tab--active' : ''}`} onClick={() => switchMode('signup')}>
              Sign up
            </button>
          </div>
        )}

        {mode === 'signup' && (
          <label className="auth-field">
            <span>Name</span>
            <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} autoComplete="name" required />
          </label>
        )}
        <label className="auth-field">
          <span>Email</span>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required autoFocus />
        </label>
        {mode !== 'sso' && <label className="auth-field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            minLength={mode === 'signup' ? 8 : undefined}
            required
          />
          {mode === 'signup' && <small>At least 8 characters.</small>}
        </label>}
        {mode === 'signup' && (
          <label className="auth-field">
            <span>Workspace name <em>(optional)</em></span>
            <input value={workspaceName} onChange={(e) => setWorkspaceName(e.target.value)} placeholder="Acme Research" />
          </label>
        )}

        {error && <div className="auth-error" role="alert">{error}</div>}

        {ssoChoices.length > 0 ? (
          <div className="auth-sso-choices">
            <small>Choose where to sign in:</small>
            {ssoChoices.map((p) => (
              <button key={p.id} type="button" className="auth-submit auth-sso-choice" onClick={() => startSso(p.id)}>
                {p.name} <em>· {p.workspace}</em>
              </button>
            ))}
          </div>
        ) : (
          <button type="submit" className="auth-submit" disabled={busy}>
            {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : mode === 'sso' ? 'Continue' : 'Create account'}
          </button>
        )}

        {mode === 'login' && (
          <button type="button" className="auth-link" onClick={() => switchMode('sso')}>
            Sign in with SSO
          </button>
        )}
        {mode === 'sso' && (
          <button type="button" className="auth-link" onClick={() => switchMode('login')}>
            Use email and password instead
          </button>
        )}
      </form>
    </div>
  )
}
