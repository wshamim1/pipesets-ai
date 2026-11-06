import { useSyncExternalStore } from 'react'
import { API_BASE } from '../types'

/**
 * Client for the encrypted secrets vault (/api/secrets).
 * Values are write-only: the server never returns them, only the name, last 4
 * characters and a "secret://<id>" reference that tool configs store instead of the key.
 */
/** llm: only model/embedding calls can use it · tool: only tools can use it (enforced server-side). */
export type SecretKind = 'llm' | 'tool'

export const SECRET_KIND_LABELS: Record<SecretKind, string> = {
  llm: 'LLM provider key',
  tool: 'Tool / integration key',
}

export const LLM_PROVIDER_SUGGESTIONS = ['openai', 'anthropic', 'groq', 'gemini', 'mistral', 'cohere', 'together',
  'fireworks', 'deepseek', 'xai', 'azure', 'bedrock', 'nvidia', 'watsonx', 'voyage', 'nomic', 'typesafe']
export const TOOL_PROVIDER_SUGGESTIONS = ['serper', 'serpapi', 'tavily', 'brave', 'exa', 'wolfram_alpha', 'slack',
  'discord', 'teams', 'google_chat', 'telegram', 'twilio', 'github', 'smtp', 'aws']

export interface SecretRecord {
  id: string
  name: string
  kind: SecretKind
  provider: string
  /** LLM provider this is the project's default key for (null = not a default). */
  default_for: string | null
  last4: string
  scope: 'project' | 'tenant'
  ref: string
  created_at: string
  updated_at: string
  last_used_at: string | null
}

export const SECRET_REF_PREFIX = 'secret://'

/** Inline-encrypted value (connection credentials); opaque to the browser. */
export const isSealed = (value: unknown): value is string => typeof value === 'string' && value.startsWith('enc://')

export const isSecretRef = (value: unknown): value is string =>
  typeof value === 'string' && /^secret:\/\/[A-Za-z0-9_-]+$/.test(value)

export const secretIdFromRef = (ref: string) => ref.slice(SECRET_REF_PREFIX.length)

// Config keys that hold credentials ("max_tokens" and the like deliberately don't match)
const SECRET_KEY_RE = /(^|_)(api_?key|token|secret|secret_key|password|app_id|webhook_url|access_key_id|secret_access_key|routing_key|integration_key)$/i
export const isSecretConfigKey = (key: string) => SECRET_KEY_RE.test(key)

/** Provider tag suggested for a tool's secret, e.g. "serper_search" → "serper". */
export const providerForTool = (toolId: string) => toolId.replace(/_(search|webhook|bot|sms|api)$/, '')

let secrets: SecretRecord[] = []
let loaded = false
let error = ''
const listeners = new Set<() => void>()
let snapshot = { secrets, loaded, error }

function commit() {
  snapshot = { secrets, loaded, error }
  listeners.forEach((fn) => fn())
}

function subscribe(fn: () => void) {
  listeners.add(fn)
  if (!loaded) void refreshSecrets()
  return () => { listeners.delete(fn) }
}

/** React hook: the vault listing for the current project, loaded on first use. */
export function useSecrets() {
  return useSyncExternalStore(subscribe, () => snapshot, () => snapshot)
}

async function request(path: string, init?: RequestInit) {
  const res = await fetch(`${API_BASE}/api/secrets${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export async function refreshSecrets() {
  try {
    secrets = await request('')
    error = ''
  } catch (e) {
    secrets = []
    error = e instanceof Error ? e.message : String(e)
  }
  loaded = true
  commit()
}

export async function createSecret(input: { name: string; value: string; kind: SecretKind; provider?: string; shared?: boolean; default_for?: string }) {
  const saved: SecretRecord = await request('', { method: 'POST', body: JSON.stringify(input) })
  if (saved.default_for) await refreshSecrets()  // claiming a default clears it on another secret
  else {
    secrets = [...secrets, saved].sort((a, b) => a.name.localeCompare(b.name))
    commit()
  }
  return saved
}

export async function updateSecret(id: string, input: { name?: string; value?: string; kind?: SecretKind; provider?: string; default_for?: string }) {
  const saved: SecretRecord = await request(`/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(input) })
  if (input.default_for) await refreshSecrets()
  else {
    secrets = secrets.map((s) => (s.id === id ? saved : s))
    commit()
  }
  return saved
}

export async function deleteSecret(id: string) {
  await request(`/${encodeURIComponent(id)}`, { method: 'DELETE' })
  secrets = secrets.filter((s) => s.id !== id)
  commit()
}
