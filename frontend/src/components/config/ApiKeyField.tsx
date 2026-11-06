import { useState } from 'react'
import { isSealed, isSecretRef, useSecrets } from '../../utils/secrets'
import type { SecretKind, SecretRecord } from '../../utils/secrets'
import { SecretModal } from '../SecretModal'

interface Props {
  /** Node's stored key: '' (use the default), a "secret://" ref, an "enc://" sealed key
   *  (a typed key from before refs were enforced), or plaintext (legacy — the server refuses to save it). */
  value: string | undefined
  onChange: (value: string) => void
  /** Provider the key is for — picks the project default and sorts matching secrets first. */
  provider: string
  readOnly?: boolean
  /** Label for the '' option when the provider has no project default. */
  emptyLabel?: string
  placeholder?: string
  /** Name prefilled for "+ New secret…". */
  secretName?: string
  /** Which secrets this field may use: 'llm' for model nodes (default), 'tool' for third-party tokens. */
  kind?: SecretKind
}

const NEW = '__new__'
const PLAIN = '__plain__'

/**
 * Key picker for model/agent nodes: project default or a vault secret. Only a "secret://"
 * ref is stored on the node — pipelines can't be saved with a key in plain text.
 */
export function ApiKeyField({ value, onChange, provider, readOnly, emptyLabel, placeholder, secretName, kind = 'llm' }: Props) {
  const { secrets } = useSecrets()
  const [modal, setModal] = useState<{ value?: string } | null>(null)
  const current = value ?? ''
  const p = provider.toLowerCase() === 'azure' ? 'openai' : provider.toLowerCase()
  const projectDefault = kind === 'llm' && p ? secrets.find((s) => s.default_for === p) : undefined
  const isRef: boolean = isSecretRef(current as unknown)
  const sealed: boolean = isSealed(current as unknown)
  const isPlain = !isRef && !sealed && current.trim() !== ''
  const referenced = isRef ? secrets.find((s) => s.ref === current) : undefined
  const missingRef = isRef && !referenced
  const wrongKind = !!referenced && referenced.kind !== kind
  // Only secrets of this field's kind (the server refuses the other kind); this provider's first
  const usable = secrets.filter((s) => s.kind === kind)
  const matching = p ? usable.filter((s) => s.provider === p) : []
  const others = usable.filter((s) => !matching.includes(s))
  const label = (s: SecretRecord) => `${s.name} ••••${s.last4}${s.scope === 'tenant' ? ' (shared)' : ''}`
  const kindName = kind === 'llm' ? 'LLM' : 'tool'

  return (
    <div className="api-key-field">
      <select
        className="field-input"
        disabled={readOnly}
        value={isRef || sealed ? current : isPlain ? PLAIN : ''}
        onChange={(e) => {
          const next = e.target.value
          if (next === NEW) setModal({})
          else if (next !== PLAIN) onChange(next)
        }}
      >
        <option value="">
          {projectDefault ? `Project default — ${projectDefault.name} ••••${projectDefault.last4}` : (emptyLabel ?? '— No key —')}
        </option>
        {sealed && <option value={current}>Encrypted key saved in this pipeline</option>}
        {isPlain && <option value={PLAIN}>⚠ Key in plain text (can't be saved)</option>}
        {missingRef && <option value={current}>⚠ Missing secret</option>}
        {wrongKind && <option value={current}>⚠ {referenced!.name} (wrong type — not allowed)</option>}
        {matching.length > 0 && (
          <optgroup label={`${provider} keys`}>
            {matching.map((s) => <option key={s.id} value={s.ref}>{label(s)}</option>)}
          </optgroup>
        )}
        {others.length > 0 && (
          <optgroup label={matching.length ? `Other ${kindName} keys` : `${kindName === 'LLM' ? 'LLM' : 'Tool'} keys`}>
            {others.map((s) => <option key={s.id} value={s.ref}>{label(s)}</option>)}
          </optgroup>
        )}
        <option value={NEW}>+ New {kindName} key…</option>
      </select>
      {isPlain && !readOnly && (
        <div className="tool-secret-warning">
          Keys can't be saved in plain text in a pipeline.
          <button type="button" onClick={() => setModal({ value: current })}>Move to Secrets</button>
        </div>
      )}
      {missingRef && (
        <div className="tool-secret-warning">This secret was deleted or belongs to another project. Pick another.</div>
      )}
      {wrongKind && (
        <div className="tool-secret-warning">
          {kind === 'llm' ? 'Tool keys can\'t be used by model calls' : 'LLM provider keys can\'t be used here'} — the run
          will refuse it. Pick {kind === 'llm' ? 'an LLM' : 'a tool'} key.
        </div>
      )}
      {modal && (
        <SecretModal
          defaults={{ name: secretName ?? `${provider} API key`, provider: p, value: modal.value, kind, placeholder }}
          lockKind
          onClose={() => setModal(null)}
          onSaved={(saved) => onChange(saved.ref)}
        />
      )}
    </div>
  )
}
