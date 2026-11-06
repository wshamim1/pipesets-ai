import { useState } from 'react'
import { API_BASE } from '../../types'
import { PROVIDER_KEY_FIELDS, useCredentials } from '../../context/CredentialsContext'

type ProviderValidationState = { status: 'idle' | 'validating' | 'ok' | 'error'; message?: string; latencyMs?: number }

/** Model provider keys: the project's default key per provider, kept in the encrypted vault. */
export function ProviderKeysPanel() {
  const { credentials, vaultBacked, providerSecret, saveProviderKey, clearProviderKey } = useCredentials()
  const anyKeySet = Object.values(credentials).some((v) => v.trim().length > 0)
  // provider -> draft value while replacing a key
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState<string | null>(null)
  const [saveError, setSaveError] = useState('')

  const save = async (provider: string) => {
    setSaving(provider)
    setSaveError('')
    try {
      await saveProviderKey(provider, drafts[provider] ?? '')
      setDrafts((prev) => { const next = { ...prev }; delete next[provider]; return next })
      setValidationByProvider((prev) => ({ ...prev, [provider]: { status: 'idle' } }))
    } catch (e) {
      setSaveError(`${provider}: ${e instanceof Error ? e.message : e}`)
    } finally {
      setSaving(null)
    }
  }
  const [validationByProvider, setValidationByProvider] = useState<Record<string, ProviderValidationState>>({})
  const [bulkValidating, setBulkValidating] = useState(false)

  const validateProvider = async (provider: string, keyField: (typeof PROVIDER_KEY_FIELDS)[number]['key']) => {
    const apiKey = (credentials[keyField] || '').trim()
    if (!apiKey) {
      setValidationByProvider((prev) => ({ ...prev, [provider]: { status: 'error', message: 'Add key first' } }))
      return
    }
    setValidationByProvider((prev) => ({ ...prev, [provider]: { status: 'validating', message: 'Testing...' } }))
    try {
      const res = await fetch(`${API_BASE}/api/providers/validate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider, api_key: apiKey }),
      })
      const payload = await res.json()
      setValidationByProvider((prev) => ({
        ...prev,
        [provider]: res.ok
          ? { status: payload.ok ? 'ok' : 'error', message: payload.message || (payload.ok ? 'Connected' : 'Failed'), latencyMs: payload.latency_ms }
          : { status: 'error', message: payload?.detail || 'Validation failed' },
      }))
    } catch {
      setValidationByProvider((prev) => ({ ...prev, [provider]: { status: 'error', message: 'Backend unreachable' } }))
    }
  }

  const validateAllSetKeys = async () => {
    const credentialsPayload = PROVIDER_KEY_FIELDS.reduce<Record<string, string>>((acc, f) => {
      const v = (credentials[f.key] || '').trim()
      if (v) acc[f.provider] = v
      return acc
    }, {})
    if (Object.keys(credentialsPayload).length === 0) return
    setBulkValidating(true)
    try {
      const res = await fetch(`${API_BASE}/api/providers/validate-all`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ credentials: credentialsPayload }),
      })
      const payload = await res.json()
      if (res.ok) {
        const next: Record<string, ProviderValidationState> = {}
        for (const item of payload.results || []) {
          next[item.provider] = { status: item.ok ? 'ok' : 'error', message: item.message || (item.ok ? 'Connected' : 'Failed'), latencyMs: item.latency_ms }
        }
        setValidationByProvider((prev) => ({ ...prev, ...next }))
      }
    } catch { /* keep existing */ } finally {
      setBulkValidating(false)
    }
  }

  const renderBadge = (provider: string) => {
    const st = validationByProvider[provider]
    if (!st || st.status === 'idle') return null
    if (st.status === 'validating') return <span className="tnav-key-badge tnav-key-badge--testing">Testing…</span>
    if (st.status === 'ok') {
      const lat = typeof st.latencyMs === 'number' && st.latencyMs > 0 ? ` · ${st.latencyMs}ms` : ''
      return <span className="tnav-key-badge tnav-key-badge--ok">OK{lat}</span>
    }
    return <span className="tnav-key-badge tnav-key-badge--err">{st.message || 'Failed'}</span>
  }

  return (
    <div className="settings-card">
      <div className="settings-card-header">
        <p className="settings-card-hint">
          {vaultBacked
            ? 'Default key per provider for this project, used by any model node without its own key. Keys are encrypted on the server and can only be replaced, never viewed.'
            : 'You don\'t have access to the secrets vault, so these keys are stored only in this browser.'}
        </p>
        <button type="button" className="ops-refresh-btn" onClick={validateAllSetKeys} disabled={!anyKeySet || bulkValidating}>
          {bulkValidating ? 'Testing…' : 'Test all'}
        </button>
      </div>
      <div className="settings-key-list">
        {PROVIDER_KEY_FIELDS.map(({ key, provider, label, placeholder }) => (
          <div key={key} className="settings-key-row">
            <label className="settings-key-label" htmlFor={`provider-key-${provider}`}>{label}</label>
            {(() => {
              const secret = providerSecret(provider)
              const editing = provider in drafts || !credentials[key]
              return editing ? (
                <>
                  <input
                    id={`provider-key-${provider}`}
                    type="password"
                    autoComplete="off"
                    className="settings-key-input"
                    value={drafts[provider] ?? ''}
                    onChange={(e) => setDrafts((prev) => ({ ...prev, [provider]: e.target.value }))}
                    onKeyDown={(e) => { if (e.key === 'Enter') void save(provider) }}
                    placeholder={placeholder}
                  />
                  <button type="button" className="ops-refresh-btn" onClick={() => save(provider)}
                    disabled={!(drafts[provider] ?? '').trim() || saving === provider}>
                    {saving === provider ? 'Saving…' : 'Save'}
                  </button>
                  {credentials[key] ? (
                    <button type="button" className="ops-link-btn"
                      onClick={() => setDrafts((prev) => { const next = { ...prev }; delete next[provider]; return next })}>
                      Cancel
                    </button>
                  ) : <span />}
                </>
              ) : (
                <>
                  <span className="settings-key-masked" id={`provider-key-${provider}`}>
                    {secret ? `•••• ${secret.last4}` : '••••••••'}{vaultBacked ? ' · encrypted' : ' · this browser'}
                  </span>
                  <button type="button" className="ops-refresh-btn"
                    onClick={() => validateProvider(provider, key)}
                    disabled={validationByProvider[provider]?.status === 'validating'}>Test</button>
                  <span className="settings-key-actions">
                    <button type="button" className="ops-link-btn"
                      onClick={() => setDrafts((prev) => ({ ...prev, [provider]: '' }))}>Replace</button>
                    <button type="button" className="ops-link-btn"
                      onClick={async () => {
                        await clearProviderKey(provider)
                        setValidationByProvider((prev) => ({ ...prev, [provider]: { status: 'idle' } }))
                      }}>Remove</button>
                  </span>
                </>
              )
            })()}
            <span className="settings-key-status">{renderBadge(provider)}</span>
          </div>
        ))}
      </div>
      {saveError && <p className="settings-card-hint" style={{ color: '#b91c1c' }}>Couldn't save {saveError}</p>}
    </div>
  )
}
