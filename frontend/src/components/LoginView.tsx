import { useEffect, useState, type FormEvent } from 'react'
import { API_BASE } from '../types'
import { useAuth } from '../context/AuthContext'
import '../styles/auth.css'

type Mode = 'login' | 'signup'

export function LoginView() {
  const { login, signup } = useAuth()
  const [mode, setMode] = useState<Mode>('login')
  const [signupEnabled, setSignupEnabled] = useState(true)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [workspaceName, setWorkspaceName] = useState('')
  const [error, setError] = useState('')
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
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      if (mode === 'login') {
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
        <h1 className="auth-title">{mode === 'login' ? 'Sign in' : 'Create your account'}</h1>
        <p className="auth-subtitle">
          {mode === 'login'
            ? 'Use the email and password for your account.'
            : 'You get your own workspace. Teammates can add you to theirs by email.'}
        </p>

        {signupEnabled && (
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
        <label className="auth-field">
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
        </label>
        {mode === 'signup' && (
          <label className="auth-field">
            <span>Workspace name <em>(optional)</em></span>
            <input value={workspaceName} onChange={(e) => setWorkspaceName(e.target.value)} placeholder="Acme Research" />
          </label>
        )}

        {error && <div className="auth-error" role="alert">{error}</div>}

        <button type="submit" className="auth-submit" disabled={busy}>
          {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
        </button>
      </form>
    </div>
  )
}
