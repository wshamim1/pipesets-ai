import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { API_BASE } from '../types'
import { AUTH_EXPIRED_EVENT, SCOPE_STORAGE_KEY, getAuthToken } from '../utils/authToken'
import { useAuth, type AuthTenant } from './AuthContext'

type ScopeState = {
  tenantId: string
  projectId: string
  userId: string
}

type UserOption = {
  id: string
  email: string
  display_name: string
  tenant_role?: string
}

type ProjectOption = {
  id: string
  name: string
  status?: string
}

type TenantOption = {
  id: string
  name: string
  slug?: string
  status?: string
}

type TenantContextValue = {
  scope: ScopeState
  tenants: TenantOption[]
  users: UserOption[]
  projects: ProjectOption[]
  loading: boolean
  /** Whether the signed-in user holds iam:admin in the current tenant */
  canAdmin: boolean
  /** Whether the signed-in user manages the server itself (Settings → Database) */
  serverAdmin: boolean
  setTenantId: (tenantId: string) => void
  setProjectId: (projectId: string) => void
  refresh: () => Promise<void>
}

const STORAGE_KEY = SCOPE_STORAGE_KEY
const defaults: ScopeState = {
  tenantId: '',
  projectId: '',
  userId: '',
}

/** Keep the stored scope only if the user still belongs to that tenant/project. */
function reconcileScope(scope: ScopeState, userId: string, memberships: AuthTenant[]): ScopeState {
  const tenant = memberships.find((t) => t.id === scope.tenantId) ?? memberships[0]
  if (!tenant) return { tenantId: '', projectId: '', userId }
  const projectId = tenant.projects.some((p) => p.id === scope.projectId)
    ? scope.projectId
    : tenant.projects[0]?.id ?? ''
  return { tenantId: tenant.id, projectId, userId }
}

function loadScope(): ScopeState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...defaults }
    const parsed = JSON.parse(raw)
    return {
      tenantId: parsed?.tenantId || defaults.tenantId,
      projectId: parsed?.projectId || defaults.projectId,
      userId: parsed?.userId || defaults.userId,
    }
  } catch {
    return { ...defaults }
  }
}

const TenantContext = createContext<TenantContextValue>({
  scope: defaults,
  tenants: [],
  users: [],
  projects: [],
  loading: false,
  canAdmin: false,
  serverAdmin: false,
  setTenantId: () => {},
  setProjectId: () => {},
  refresh: async () => {},
})

function injectContextHeaders(input: RequestInfo | URL, init?: RequestInit): [RequestInfo | URL, RequestInit | undefined] {
  const toURL = (value: RequestInfo | URL): string => {
    if (typeof value === 'string') return value
    if (value instanceof URL) return value.toString()
    return value.url
  }

  const url = toURL(input)
  if (!url.startsWith(API_BASE)) return [input, init]

  let scope = defaults
  try {
    scope = loadScope()
  } catch {
    scope = defaults
  }

  const mergedHeaders = new Headers(
    init?.headers ??
    (typeof Request !== 'undefined' && input instanceof Request ? input.headers : undefined),
  )
  // Identity comes from the session token; the server ignores x-user-id once signed in
  const token = getAuthToken()
  if (token && !mergedHeaders.has('authorization')) mergedHeaders.set('authorization', `Bearer ${token}`)
  if (scope.tenantId) mergedHeaders.set('x-tenant-id', scope.tenantId)
  if (scope.projectId) mergedHeaders.set('x-project-id', scope.projectId)

  if (typeof Request !== 'undefined' && input instanceof Request) {
    const nextRequest = new Request(input, { headers: mergedHeaders })
    return [nextRequest, init]
  }

  return [input, { ...(init ?? {}), headers: mergedHeaders }]
}

function installFetchContextInjector() {
  const w = window as any
  if (w.__univFetchWrapped) return
  const originalFetch = window.fetch.bind(window)
  w.__univOriginalFetch = originalFetch
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const [nextInput, nextInit] = injectContextHeaders(input, init)
    const res = await originalFetch(nextInput as any, nextInit)
    // A 401 from our API means the session is gone (expired, revoked, user disabled)
    const url = typeof nextInput === 'string' ? nextInput : nextInput instanceof URL ? nextInput.toString() : nextInput.url
    if (res.status === 401 && url.startsWith(API_BASE) && !/\/api\/auth\/(login|signup)$/.test(url) && getAuthToken()) {
      window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT))
    }
    return res
  }
  w.__univFetchWrapped = true
}

// Installed at import time so the very first request (AuthProvider's /me) carries the token
installFetchContextInjector()

export function TenantProvider({ children }: { children: ReactNode }) {
  const { user, tenants: initialMemberships } = useAuth()
  const userId = user?.id ?? ''
  const [scope, setScope] = useState<ScopeState>(() => reconcileScope(loadScope(), userId, initialMemberships))
  const scopeRef = useRef(scope)
  const membershipsRef = useRef<AuthTenant[]>(initialMemberships)
  const [canAdmin, setCanAdmin] = useState(false)
  const [serverAdmin, setServerAdmin] = useState(false)
  const [tenants, setTenants] = useState<TenantOption[]>([])
  const [users, setUsers] = useState<UserOption[]>([])
  const [projects, setProjects] = useState<ProjectOption[]>([])
  const [loading, setLoading] = useState(false)

  const persistScope = useCallback((next: ScopeState) => {
    const cur = scopeRef.current
    if (cur.tenantId === next.tenantId && cur.projectId === next.projectId && cur.userId === next.userId) return
    scopeRef.current = next
    setScope(next)
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    } catch {
      // ignore
    }
  }, [])

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      // Fresh memberships first (they change when tenants/projects are created), so the
      // scope is valid before any tenant-scoped request goes out with it
      const meRes = await fetch(`${API_BASE}/api/auth/me`)
      if (meRes.ok) membershipsRef.current = (await meRes.json())?.tenants ?? []
      persistScope(reconcileScope(scopeRef.current, userId, membershipsRef.current))
      if (!scopeRef.current.tenantId) return

      const [tenantsRes, ctxRes, usersRes, projectsRes] = await Promise.all([
        fetch(`${API_BASE}/api/iam/tenants`),
        fetch(`${API_BASE}/api/iam/context`),
        fetch(`${API_BASE}/api/iam/users`),
        fetch(`${API_BASE}/api/iam/projects`),
      ])
      if (tenantsRes.ok) setTenants((await tenantsRes.json())?.tenants ?? [])
      if (ctxRes.ok) {
        const ctx = await ctxRes.json()
        setCanAdmin(Boolean(ctx?.can_admin))
        setServerAdmin(Boolean(ctx?.server_admin))
      }
      if (usersRes.ok) setUsers((await usersRes.json())?.users ?? [])
      if (projectsRes.ok) setProjects((await projectsRes.json())?.projects ?? [])
    } catch {
      // keep the current scope when the backend is not available
    } finally {
      setLoading(false)
    }
  }, [persistScope, userId])

  // Reload on sign-in and whenever the tenant changes (users/projects are per tenant)
  useEffect(() => {
    refresh()
  }, [refresh, scope.tenantId])

  const value = useMemo<TenantContextValue>(() => ({
    scope,
    tenants,
    users,
    projects,
    loading,
    canAdmin,
    serverAdmin,
    // Switching tenant also picks a project that belongs to it
    setTenantId: (tenantId: string) => persistScope(reconcileScope({ ...scope, tenantId }, userId, membershipsRef.current)),
    setProjectId: (projectId: string) => persistScope({ ...scope, projectId }),
    refresh,
  }), [canAdmin, serverAdmin, loading, persistScope, projects, refresh, scope, tenants, userId, users])

  return (
    <TenantContext.Provider value={value}>
      {children}
    </TenantContext.Provider>
  )
}

export function useTenantContext() {
  return useContext(TenantContext)
}
