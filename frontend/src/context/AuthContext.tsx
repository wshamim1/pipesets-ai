import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { API_BASE } from '../types'
import { AUTH_EXPIRED_EVENT, clearStoredScope, getAuthToken, setAuthToken } from '../utils/authToken'
import { LoginView } from '../components/LoginView'

export type AuthUser = {
  id: string
  email: string
  display_name: string
}

export type AuthTenant = {
  id: string
  name: string
  slug?: string
  role: string
  projects: Array<{ id: string; name: string; status?: string }>
}

type SignupInput = { email: string; password: string; display_name: string; workspace_name?: string }

type AuthContextValue = {
  user: AuthUser | null
  tenants: AuthTenant[]
  login: (email: string, password: string) => Promise<void>
  signup: (input: SignupInput) => Promise<void>
  logout: () => Promise<void>
  refreshMe: () => Promise<void>
  /** Why the last single sign-on attempt failed (from the IdP round trip), shown on the sign-in screen. */
  ssoError: string
  /** True when this session was opened by single sign-on (it reaches only that workspace). */
  ssoSession: boolean
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  tenants: [],
  login: async () => {},
  signup: async () => {},
  logout: async () => {},
  refreshMe: async () => {},
  ssoError: '',
  ssoSession: false,
})

/** Reads and removes ?sso_code / ?sso_error, which the backend adds when SSO sends the browser back. */
function takeSsoParams(): { code: string; error: string } {
  const url = new URL(window.location.href)
  const code = url.searchParams.get('sso_code') ?? ''
  const error = url.searchParams.get('sso_error') ?? ''
  if (code || error) {
    url.searchParams.delete('sso_code')
    url.searchParams.delete('sso_error')
    window.history.replaceState(window.history.state, '', url.pathname + url.search + url.hash)
  }
  return { code, error }
}

async function errorDetail(res: Response, fallback: string): Promise<string> {
  try {
    const payload = await res.json()
    return typeof payload?.detail === 'string' ? payload.detail : fallback
  } catch {
    return fallback
  }
}

/** Renders the sign-in screen until there is a valid session, then its children. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [sso] = useState(takeSsoParams)
  const [ssoError, setSsoError] = useState(sso.error)
  const [ssoSession, setSsoSession] = useState(false)
  const [status, setStatus] = useState<'loading' | 'anon' | 'authed'>(getAuthToken() || sso.code ? 'loading' : 'anon')
  const [user, setUser] = useState<AuthUser | null>(null)
  const [tenants, setTenants] = useState<AuthTenant[]>([])

  const applyMe = useCallback((data: any) => {
    setUser(data.user)
    setTenants(data.tenants ?? [])
    setSsoSession(Boolean(data.session?.sso))
    setStatus('authed')
  }, [])

  const signOutLocally = useCallback(() => {
    setAuthToken(null)
    clearStoredScope()
    setUser(null)
    setTenants([])
    setStatus('anon')
  }, [])

  const refreshMe = useCallback(async () => {
    if (!getAuthToken()) {
      signOutLocally()
      return
    }
    try {
      const res = await fetch(`${API_BASE}/api/auth/me`)
      if (res.ok) applyMe(await res.json())
      else if (res.status === 401) signOutLocally()
    } catch {
      // backend unreachable: keep the token and show the sign-in screen
      setStatus((s) => (s === 'loading' ? 'anon' : s))
    }
  }, [applyMe, signOutLocally])

  useEffect(() => {
    window.addEventListener(AUTH_EXPIRED_EVENT, signOutLocally)
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, signOutLocally)
  }, [signOutLocally])

  const startSession = useCallback(async (path: string, body: unknown, fallback: string) => {
    const res = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) throw new Error(await errorDetail(res, fallback))
    const data = await res.json()
    clearStoredScope() // the previous user's tenant/project may not be ours
    setAuthToken(data.token)
    applyMe(data)
  }, [applyMe])

  // Back from single sign-on with a one-time code: trade it for a session (once — the code is single-use,
  // and StrictMode runs effects twice). Otherwise check the saved session.
  const exchanged = useRef(false)
  useEffect(() => {
    if (!sso.code) {
      refreshMe()
      return
    }
    if (exchanged.current) return
    exchanged.current = true
    startSession('/api/auth/sso/exchange', { code: sso.code }, 'Single sign-on failed')
      .catch((err) => {
        setSsoError(err instanceof Error ? err.message : 'Single sign-on failed')
        setStatus('anon')
      })
  }, [refreshMe, startSession, sso.code])

  const value = useMemo<AuthContextValue>(() => ({
    user,
    tenants,
    login: (email, password) => startSession('/api/auth/login', { email, password }, 'Sign-in failed'),
    signup: (input) => startSession('/api/auth/signup', input, 'Sign-up failed'),
    logout: async () => {
      try {
        await fetch(`${API_BASE}/api/auth/logout`, { method: 'POST' })
      } finally {
        signOutLocally()
      }
    },
    refreshMe,
    ssoError,
    ssoSession,
  }), [refreshMe, signOutLocally, ssoError, ssoSession, startSession, tenants, user])

  if (status === 'loading') {
    return <div className="auth-splash">Loading…</div>
  }

  return (
    <AuthContext.Provider value={value}>
      {status === 'authed' ? children : <LoginView />}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
