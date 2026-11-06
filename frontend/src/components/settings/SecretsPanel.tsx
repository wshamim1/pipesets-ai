import { useState } from 'react'
import { KeyRound, Pencil, Trash2 } from 'lucide-react'
import { deleteSecret, refreshSecrets, SECRET_KIND_LABELS, useSecrets } from '../../utils/secrets'
import type { SecretKind, SecretRecord } from '../../utils/secrets'
import { SecretModal } from '../SecretModal'

const KIND_HINTS: Record<SecretKind, string> = {
  llm: 'Model and embedding calls only — never visible to tools. Defaults are managed under Model provider keys.',
  tool: 'Tools only (search APIs, webhooks, bots, business apps) — never visible to model calls.',
}

const fmtDate = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString() : 'never')

/** Settings page for the encrypted secrets vault of the current project. */
export function SecretsPanel() {
  const { secrets, loaded, error } = useSecrets()
  const [modal, setModal] = useState<{ secret?: SecretRecord; kind?: SecretKind } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const remove = async (s: SecretRecord) => {
    const warning = s.default_for
      ? `"${s.name}" is the default ${s.default_for} key — model nodes without their own key will stop working.`
      : `Tools and nodes that use "${s.name}" will stop working.`
    if (!window.confirm(`Delete secret "${s.name}"?\n\n${warning}`)) return
    setBusy(s.id)
    try {
      await deleteSecret(s.id)
    } catch (e) {
      window.alert(`Couldn't delete: ${e instanceof Error ? e.message : e}`)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="secrets-settings">
      <div className="settings-card">
        <div className="settings-card-header">
          <p className="settings-card-hint">
            API keys, tokens and webhook URLs for this project, encrypted on the server. Values can't be viewed after
            saving — only replaced. Nodes store a reference, so keys never appear in pipelines, exports or shares.
            You can also create a secret straight from any key field on the canvas.
          </p>
          <button type="button" className="ops-refresh-btn" onClick={() => void refreshSecrets()}>Refresh</button>
        </div>
        {loaded && error && <p className="settings-card-hint" style={{ color: '#b91c1c' }}>Can't load secrets: {error}</p>}
      </div>

      {(Object.keys(SECRET_KIND_LABELS) as SecretKind[]).map((kind) => {
        const rows = secrets.filter((s) => s.kind === kind)
        return (
          <div key={kind} className="settings-card">
            <div className="settings-card-header">
              <div>
                <h3 className="secrets-kind-title">
                  <span className={`connection-icon secret-icon secret-icon--${kind}`}><KeyRound size={12} aria-hidden="true" /></span>
                  {SECRET_KIND_LABELS[kind]}s
                  <span className="secrets-kind-count">{rows.length}</span>
                </h3>
                <p className="settings-card-hint">{KIND_HINTS[kind]}</p>
              </div>
              <button type="button" className="ops-refresh-btn" onClick={() => setModal({ kind })}>
                + Add {kind === 'llm' ? 'LLM' : 'tool'} key
              </button>
            </div>
            {rows.length === 0 ? (
              <p className="settings-card-hint secrets-empty">{loaded ? 'None yet.' : 'Loading…'}</p>
            ) : (
              <div className="secrets-table" role="table">
                <div className="secrets-row secrets-row--head" role="row">
                  <span role="columnheader">Name</span>
                  <span role="columnheader">Provider</span>
                  <span role="columnheader">Value</span>
                  <span role="columnheader">Scope</span>
                  <span role="columnheader">Last used</span>
                  <span role="columnheader">Updated</span>
                  <span />
                </div>
                {rows.map((s) => (
                  <div key={s.id} className="secrets-row" role="row">
                    <span className="secrets-name" title={s.ref}>
                      {s.name}
                      {s.default_for && <span className="secrets-badge">default {s.default_for}</span>}
                    </span>
                    <span>{s.provider || '—'}</span>
                    <span className="secrets-mono">••••{s.last4}</span>
                    <span>{s.scope === 'tenant' ? 'Shared (all projects)' : 'This project'}</span>
                    <span>{fmtDate(s.last_used_at)}</span>
                    <span>{fmtDate(s.updated_at)}</span>
                    <span className="secrets-actions">
                      <button type="button" className="ct-card-action-btn" title="Rename or replace value"
                        onClick={() => setModal({ secret: s })}><Pencil aria-hidden="true" /></button>
                      <button type="button" className="ct-card-action-btn delete" title="Delete" disabled={busy === s.id}
                        onClick={() => remove(s)}><Trash2 aria-hidden="true" /></button>
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )
      })}

      {modal && (
        <SecretModal
          secret={modal.secret}
          defaults={modal.kind ? { kind: modal.kind } : undefined}
          lockKind={!!modal.kind}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  )
}
