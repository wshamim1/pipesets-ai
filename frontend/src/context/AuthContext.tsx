import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
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
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  tenants: [],
  login: async () => {},
  signup: async () => {},
  logout: async () => {},
  refreshMe: async () => {},
})

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
  const [status, setStatus] = useState<'loading' | 'anon' | 'authed'>(getAuthToken() ? 'loading' : 'anon')
  const [user, setUser] = useState<AuthUser | null>(null)
  const [tenants, setTenants] = useState<AuthTenant[]>([])

  const applyMe = useCallback((data: any) => {
    setUser(data.user)
    setTenants(data.tenants ?? [])
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
    refreshMe()
  }, [refreshMe])

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
  }), [refreshMe, signOutLocally, startSession, tenants, user])

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
