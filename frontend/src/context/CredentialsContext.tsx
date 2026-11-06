/**
 * CredentialsContext — model provider API keys.
 *
 * Keys live in the encrypted secrets vault on the server: each provider's key is the
 * project's default secret for that provider (default_for). The browser only ever holds
 * the "secret://<id>" reference, which the backend decrypts at the LLM call.
 *
 * Keys saved in localStorage by older versions are uploaded to the vault once and then
 * removed. Users without vault access (no `secrets` ACL) keep the old behaviour: keys
 * stored in this browser only.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createSecret, updateSecret, useSecrets } from '../utils/secrets'
import type { SecretRecord } from '../utils/secrets'

export type ProviderKeyField = { key: keyof PipelineCredentials; provider: string; label: string; placeholder: string }

export interface PipelineCredentials {
  openai_api_key: string
  anthropic_api_key: string
  groq_api_key: string
  gemini_api_key: string
  mistral_api_key: string
  together_api_key: string
  huggingface_api_key: string
  fireworks_api_key: string
  deepseek_api_key: string
  xai_api_key: string
  cerebras_api_key: string
  perplexity_api_key: string
  cohere_api_key: string
  azure_api_key: string
  nvidia_api_key: string
  watsonx_api_key: string
  typesafe_api_key: string
}

export const PROVIDER_KEY_FIELDS: ProviderKeyField[] = [
  { key: 'openai_api_key', provider: 'openai', label: 'OpenAI', placeholder: 'sk-...' },
  { key: 'anthropic_api_key', provider: 'anthropic', label: 'Anthropic', placeholder: 'sk-ant-...' },
  { key: 'groq_api_key', provider: 'groq', label: 'Groq', placeholder: 'gsk_...' },
  { key: 'gemini_api_key', provider: 'gemini', label: 'Gemini', placeholder: 'AIza...' },
  { key: 'mistral_api_key', provider: 'mistral', label: 'Mistral', placeholder: 'mis_...' },
  { key: 'together_api_key', provider: 'together', label: 'Together AI', placeholder: 'tog_...' },
  { key: 'huggingface_api_key', provider: 'huggingface', label: 'Hugging Face', placeholder: 'hf_...' },
  { key: 'fireworks_api_key', provider: 'fireworks', label: 'Fireworks', placeholder: 'fw_...' },
  { key: 'deepseek_api_key', provider: 'deepseek', label: 'DeepSeek', placeholder: 'sk-...' },
  { key: 'xai_api_key', provider: 'xai', label: 'xAI', placeholder: 'xai-...' },
  { key: 'cerebras_api_key', provider: 'cerebras', label: 'Cerebras', placeholder: 'csk_...' },
  { key: 'perplexity_api_key', provider: 'perplexity', label: 'Perplexity', placeholder: 'pplx_...' },
  { key: 'cohere_api_key', provider: 'cohere', label: 'Cohere', placeholder: 'co_...' },
  { key: 'azure_api_key', provider: 'azure', label: 'Azure OpenAI', placeholder: 'azure-...' },
  { key: 'nvidia_api_key', provider: 'nvidia', label: 'NVIDIA NIM', placeholder: 'nvapi-...' },
  { key: 'watsonx_api_key', provider: 'watsonx', label: 'IBM watsonx.ai', placeholder: 'wxa-...' },
  { key: 'typesafe_api_key', provider: 'typesafe', label: 'TypeSafe', placeholder: 'ts-...' },
]

export const PROVIDER_LABELS: Record<string, string> = Object.fromEntries(
  PROVIDER_KEY_FIELDS.map((f) => [f.provider, f.label]),
)

const STORAGE_KEY = 'univ_pipeline_credentials'

const defaults: PipelineCredentials = {
  openai_api_key: '',
  anthropic_api_key: '',
  groq_api_key: '',
  gemini_api_key: '',
  mistral_api_key: '',
  together_api_key: '',
  huggingface_api_key: '',
  fireworks_api_key: '',
  deepseek_api_key: '',
  xai_api_key: '',
  cerebras_api_key: '',
  perplexity_api_key: '',
  cohere_api_key: '',
  azure_api_key: '',
  nvidia_api_key: '',
  watsonx_api_key: '',
  typesafe_api_key: '',
}

const providerOf = (field: keyof PipelineCredentials) => field.replace(/_api_key$/, '')
const fieldOf = (provider: string) => `${provider}_api_key` as keyof PipelineCredentials

function loadLocal(): PipelineCredentials {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return { ...defaults, ...JSON.parse(raw) }
  } catch { /* ignore */ }
  return { ...defaults }
}

function saveLocal(creds: PipelineCredentials | null) {
  try {
    if (creds && Object.values(creds).some(Boolean)) localStorage.setItem(STORAGE_KEY, JSON.stringify(creds))
    else localStorage.removeItem(STORAGE_KEY)
  } catch { /* storage unavailable */ }
}

interface CredentialsContextValue {
  /** Per provider: a "secret://" ref (vault) or the key itself (browser-only fallback); '' = not set. */
  credentials: PipelineCredentials
  /** True when keys are kept in the encrypted vault; false = this browser only (no vault access). */
  vaultBacked: boolean
  /** The vault secret holding a provider's key, for showing ••••last4. */
  providerSecret: (provider: string) => SecretRecord | undefined
  /** Store (or replace) a provider's key. */
  saveProviderKey: (provider: string, value: string) => Promise<void>
  /** Stop using a key for the provider (the secret itself stays in the vault). */
  clearProviderKey: (provider: string) => Promise<void>
  /** Return the right key for a provider, falling back to the global store. */
  resolveApiKey: (provider: string, nodeKey?: string) => string
}

const CredentialsContext = createContext<CredentialsContextValue>({
  credentials: defaults,
  vaultBacked: false,
  providerSecret: () => undefined,
  saveProviderKey: async () => {},
  clearProviderKey: async () => {},
  resolveApiKey: () => '',
})

export function CredentialsProvider({ children }: { children: ReactNode }) {
  const { secrets, loaded, error } = useSecrets()
  const vaultBacked = loaded && !error
  const [local, setLocal] = useState<PipelineCredentials>(loadLocal)
  const migrating = useRef(false)

  const providerSecret = useCallback(
    (provider: string) => secrets.find((s) => s.default_for === provider.toLowerCase()),
    [secrets],
  )

  // One-time upload of keys an older version kept in localStorage
  useEffect(() => {
    if (!vaultBacked || migrating.current) return
    const pending = (Object.keys(local) as (keyof PipelineCredentials)[])
      .filter((f) => local[f].trim() && !local[f].startsWith('secret://'))
    if (pending.length === 0) {
      saveLocal(null)
      return
    }
    migrating.current = true
    void (async () => {
      const left = { ...local }
      for (const field of pending) {
        const provider = providerOf(field)
        try {
          if (!providerSecret(provider)) {
            await createSecret({
              name: `${PROVIDER_LABELS[provider] ?? provider} API key`, value: local[field].trim(),
              kind: 'llm', provider, default_for: provider,
            })
          }
          left[field] = ''
        } catch { /* keep it local; retried next load */ }
      }
      saveLocal(left)
      setLocal(left)
      migrating.current = false
    })()
  }, [vaultBacked, local, providerSecret])

  const credentials = useMemo<PipelineCredentials>(() => {
    if (!vaultBacked) return local
    const next = { ...defaults }
    for (const field of Object.keys(defaults) as (keyof PipelineCredentials)[]) {
      next[field] = providerSecret(providerOf(field))?.ref ?? ''
    }
    return next
  }, [vaultBacked, local, providerSecret])

  const saveProviderKey = useCallback(async (provider: string, value: string) => {
    const key = value.trim()
    if (!key) return
    if (!vaultBacked) {
      setLocal((prev) => {
        const next = { ...prev, [fieldOf(provider)]: key }
        saveLocal(next)
        return next
      })
      return
    }
    const existing = providerSecret(provider)
    if (existing) await updateSecret(existing.id, { value: key })
    else await createSecret({ name: `${PROVIDER_LABELS[provider] ?? provider} API key`, value: key, kind: 'llm', provider, default_for: provider })
  }, [vaultBacked, providerSecret])

  const clearProviderKey = useCallback(async (provider: string) => {
    if (!vaultBacked) {
      setLocal((prev) => {
        const next = { ...prev, [fieldOf(provider)]: '' }
        saveLocal(next)
        return next
      })
      return
    }
    const existing = providerSecret(provider)
    if (existing) await updateSecret(existing.id, { default_for: '' })
  }, [vaultBacked, providerSecret])

  const resolveApiKey = useCallback(
    (provider: string, nodeKey?: string): string => {
      if (nodeKey && nodeKey.trim()) return nodeKey.trim()
      const p = provider.toLowerCase()
      if (p === 'jev') return credentials.typesafe_api_key
      if (p === 'azure') return credentials.azure_api_key || credentials.openai_api_key
      return credentials[fieldOf(p)] || ''
    },
    [credentials],
  )

  return (
    <CredentialsContext.Provider
      value={{ credentials, vaultBacked, providerSecret, saveProviderKey, clearProviderKey, resolveApiKey }}
    >
      {children}
    </CredentialsContext.Provider>
  )
}

export function useCredentials() {
  return useContext(CredentialsContext)
}
