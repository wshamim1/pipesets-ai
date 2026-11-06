// Session token storage shared by AuthContext and the fetch injector in TenantContext.

const TOKEN_KEY = 'univ_auth_token'
export const SCOPE_STORAGE_KEY = 'univ_request_scope'
export const AUTH_EXPIRED_EVENT = 'univ-auth-expired'

export function getAuthToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setAuthToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    // storage unavailable (private mode) — the session lasts until reload
  }
}

/** Forget the selected tenant/project — it belonged to whoever was signed in. */
export function clearStoredScope() {
  try {
    localStorage.removeItem(SCOPE_STORAGE_KEY)
  } catch {
    // ignore
  }
}
