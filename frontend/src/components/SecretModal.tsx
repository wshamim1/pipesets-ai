import { useState } from 'react'
import {
  createSecret, updateSecret,
  LLM_PROVIDER_SUGGESTIONS, SECRET_KIND_LABELS, TOOL_PROVIDER_SUGGESTIONS,
} from '../utils/secrets'
import type { SecretKind, SecretRecord } from '../utils/secrets'

interface Props {
  /** Existing secret to rename / replace; omit to create one. */
  secret?: SecretRecord
  /** Prefill for a new secret (e.g. from a tool's "+ New secret"). */
  /** placeholder: hint for the value field, e.g. the provider's key format ("sk-…"). */
  defaults?: { name?: string; provider?: string; value?: string; kind?: SecretKind; placeholder?: string }
  /** Fix the type (pickers create the kind they can use). */
  lockKind?: boolean
  onClose: () => void
  onSaved?: (secret: SecretRecord) => void
}

const KIND_HINTS: Record<SecretKind, string> = {
  llm: 'Only model and embedding calls can use it — tools never see it.',
  tool: 'Only tools can use it (search APIs, webhooks, bots…) — model calls never see it.',
}

export function SecretModal({ secret, defaults, lockKind, onClose, onSaved }: Props) {
  const isEdit = !!secret
  const [name, setName] = useState(secret?.name ?? defaults?.name ?? '')
  const [kind, setKind] = useState<SecretKind>(secret?.kind ?? defaults?.kind ?? 'tool')
  const [provider, setProvider] = useState(secret?.provider ?? defaults?.provider ?? '')
  const [value, setValue] = useState(defaults?.value ?? '')
  const [shared, setShared] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  // A provider default must stay an LLM key
  const kindLocked = lockKind || !!secret?.default_for

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim() || (!isEdit && !value)) return
    setSaving(true)
    setError('')
    try {
      const saved = isEdit
        ? await updateSecret(secret!.id, {
          name: name.trim(), provider: provider.trim(), ...(kind !== secret!.kind ? { kind } : {}), ...(value ? { value } : {}),
        })
        : await createSecret({ name: name.trim(), value, kind, provider: provider.trim(), shared })
      onSaved?.(saved)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setSaving(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <form className="modal-card" onSubmit={save}>
        <div className="modal-header">
          <h3>{isEdit ? `Edit secret: ${secret!.name}` : 'New secret'}</h3>
          <button type="button" className="modal-close-btn" onClick={onClose}>✕</button>
        </div>
        <div className="modal-form">
          {error && <div className="ct-save-error">{error}</div>}
          <div className="form-group">
            <label className="field-label">Type</label>
            <div className="secret-kind-toggle" role="radiogroup">
              {(Object.keys(SECRET_KIND_LABELS) as SecretKind[]).map((k) => (
                <button key={k} type="button" role="radio" aria-checked={kind === k}
                  className={`secret-kind-option${kind === k ? ' active' : ''}`}
                  disabled={kindLocked && kind !== k} onClick={() => setKind(k)}>
                  {SECRET_KIND_LABELS[k]}
                </button>
              ))}
            </div>
            <span className="field-hint">{KIND_HINTS[kind]}</span>
          </div>
          <div className="form-group">
            <label className="field-label">Name *</label>
            <input className="field-input" value={name} onChange={(e) => setName(e.target.value)}
              placeholder={kind === 'llm' ? 'e.g. OpenAI (prod)' : 'e.g. Serper (prod)'} required autoFocus />
          </div>
          <div className="form-group">
            <label className="field-label">Provider</label>
            <input className="field-input" value={provider} onChange={(e) => setProvider(e.target.value)}
              list={`secret-providers-${kind}`} placeholder={kind === 'llm' ? 'e.g. openai, anthropic' : 'e.g. serper, slack'} />
            <datalist id={`secret-providers-${kind}`}>
              {(kind === 'llm' ? LLM_PROVIDER_SUGGESTIONS : TOOL_PROVIDER_SUGGESTIONS).map((p) => <option key={p} value={p} />)}
            </datalist>
          </div>
          <div className="form-group">
            <label className="field-label">{isEdit ? 'New value' : 'Value *'}</label>
            <input className="field-input font-mono" type="password" autoComplete="off" value={value}
              onChange={(e) => setValue(e.target.value)} required={!isEdit}
              placeholder={isEdit ? `Leave blank to keep ••••${secret!.last4}` : (defaults?.placeholder || 'Paste the API key or token')} />
            <span className="field-hint">Encrypted on the server. It can't be viewed again, only replaced.</span>
          </div>
          {!isEdit && (
            <label className="secret-shared-toggle">
              <input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} />
              Share with every project in this workspace
            </label>
          )}
        </div>
        <div className="modal-actions">
          <button type="button" className="modal-cancel-btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="modal-create-btn" disabled={saving || !name.trim() || (!isEdit && !value)}>
            {saving ? 'Saving…' : isEdit ? 'Save' : 'Save secret'}
          </button>
        </div>
      </form>
    </div>
  )
}
