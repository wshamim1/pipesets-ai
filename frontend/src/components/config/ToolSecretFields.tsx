import { useState } from 'react'
import { KeyRound } from 'lucide-react'
import { isSealed, isSecretConfigKey, isSecretRef, providerForTool, useSecrets } from '../../utils/secrets'
import { requiredConfigFor } from '../../utils/toolCatalog'
import { SecretModal } from '../SecretModal'

interface Props {
  toolId: string
  toolLabel: string
  config: Record<string, any>
  readOnly?: boolean
  onChange: (patch: Record<string, any>) => void
}

const NEW = '__new__'
const PLAIN = '__plain__'

/**
 * One picker per credential field in a tool's config. Choosing a vault secret stores its
 * "secret://<id>" reference; the backend substitutes the real value when the tool runs.
 */
export function ToolSecretFields({ toolId, toolLabel, config, readOnly, onChange }: Props) {
  const { secrets } = useSecrets()
  const [modal, setModal] = useState<{ key: string; value?: string } | null>(null)
  const keys = Object.keys(config).filter(isSecretConfigKey)
  if (keys.length === 0) return null

  const required = new Set(requiredConfigFor(toolId))
  const provider = providerForTool(toolId)

  return (
    <div className="form-group tool-secret-fields">
      <label className="field-label"><KeyRound size={12} aria-hidden="true" /> Credentials</label>
      {keys.map((key) => {
        const value = config[key]
        const isRef = isSecretRef(value)
        const sealed = isSealed(value)
        const isPlain = !isRef && !sealed && String(value ?? '').trim() !== ''
        const referenced = isRef ? secrets.find((s) => s.ref === value) : undefined
        const missingRef = isRef && !referenced
        const wrongKind = referenced?.kind === 'llm'
        // Tools can only use tool keys (the server refuses LLM keys); this provider's first
        const toolKeys = secrets.filter((s) => s.kind === 'tool')
        const matching = toolKeys.filter((s) => s.provider === provider)
        const others = toolKeys.filter((s) => s.provider !== provider)
        const label = (s: typeof secrets[number]) => `${s.name} ••••${s.last4}${s.scope === 'tenant' ? ' (shared)' : ''}`
        return (
          <div key={key} className="tool-secret-row">
            <span className="tool-secret-key">
              {key}{required.has(key) && <span className="tool-secret-required" title="Required">*</span>}
            </span>
            <select
              className="field-input tool-secret-select"
              disabled={readOnly}
              value={isRef || sealed ? value : isPlain ? PLAIN : ''}
              onChange={(e) => {
                const next = e.target.value
                if (next === NEW) setModal({ key })
                else if (next !== PLAIN) onChange({ [key]: next })
              }}
            >
              <option value="">— Not set —</option>
              {sealed && <option value={value}>Encrypted value saved in this pipeline</option>}
              {isPlain && <option value={PLAIN}>⚠ Plain text (can't be saved)</option>}
              {missingRef && <option value={value}>⚠ Missing secret</option>}
              {wrongKind && <option value={value}>⚠ {referenced!.name} (LLM key — not allowed)</option>}
              {matching.length > 0 && (
                <optgroup label={`${provider} keys`}>
                  {matching.map((s) => <option key={s.id} value={s.ref}>{label(s)}</option>)}
                </optgroup>
              )}
              {others.length > 0 && (
                <optgroup label={matching.length ? 'Other tool keys' : 'Tool keys'}>
                  {others.map((s) => <option key={s.id} value={s.ref}>{label(s)}</option>)}
                </optgroup>
              )}
              <option value={NEW}>+ New tool key…</option>
            </select>
            {isPlain && !readOnly && (
              <div className="tool-secret-warning">
                Credentials can't be saved in plain text in a pipeline.
                <button type="button" onClick={() => setModal({ key, value: String(value) })}>Move to Secrets</button>
              </div>
            )}
            {missingRef && (
              <div className="tool-secret-warning">This secret was deleted or belongs to another project. Pick another.</div>
            )}
            {wrongKind && (
              <div className="tool-secret-warning">LLM provider keys can't be used by tools — the run will refuse it. Pick a tool key.</div>
            )}
          </div>
        )
      })}
      {modal && (
        <SecretModal
          defaults={{ name: `${toolLabel} ${modal.key.replace(/_/g, ' ')}`, provider, value: modal.value, kind: 'tool' }}
          lockKind
          onClose={() => setModal(null)}
          onSaved={(saved) => onChange({ [modal.key]: saved.ref })}
        />
      )}
    </div>
  )
}
