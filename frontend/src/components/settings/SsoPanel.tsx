import { useCallback, useEffect, useState, type ChangeEvent, type FormEvent } from 'react'
import { API_BASE } from '../../types'
import { certificateFromBytes, parseSamlMetadata } from '../../utils/samlMetadata'
import { HelpLink } from '../docs/HelpLink'
import '../../styles/sso.css'

type Role = 'owner' | 'editor' | 'viewer'
type Mapping = { value: string; role: Role | ''; group_id: string }

type Provider = {
  id: string
  name: string
  protocol: 'oidc' | 'saml'
  enabled: boolean
  config: Record<string, string | boolean>
  email_domains: string[]
  role_claim: string
  role_mappings: Mapping[]
  default_role: Role | ''
  auto_provision: boolean
  sync_roles: boolean
  enforce: boolean
  redirect_uri?: string
  sp_entity_id?: string
  acs_url?: string
  metadata_url?: string
}

type Draft = Omit<Provider, 'id' | 'config' | 'email_domains'> & { id?: string; config: Record<string, string>; domains: string }

const FIELDS: Record<Provider['protocol'], { key: string; label: string; placeholder?: string; secret?: boolean; multiline?: boolean; hint?: string }[]> = {
  oidc: [
    { key: 'issuer', label: 'Issuer URL', placeholder: 'https://login.example.com/realms/acme', hint: 'Its /.well-known/openid-configuration must exist.' },
    { key: 'client_id', label: 'Client ID' },
    { key: 'client_secret', label: 'Client secret', secret: true },
    { key: 'scopes', label: 'Scopes', placeholder: 'openid email profile' },
    { key: 'email_claim', label: 'Email claim', placeholder: 'email' },
    { key: 'name_claim', label: 'Name claim', placeholder: 'name' },
  ],
  saml: [
    { key: 'idp_entity_id', label: 'IdP entity ID (Issuer)', placeholder: 'https://sts.windows.net/…/' },
    { key: 'idp_sso_url', label: 'IdP single sign-on URL', placeholder: 'https://idp.example.com/sso/saml' },
    { key: 'idp_certificate', label: 'IdP signing certificate (PEM)', multiline: true, placeholder: '-----BEGIN CERTIFICATE-----' },
    { key: 'email_attribute', label: 'Email attribute', placeholder: 'email (else NameID when it is an email)' },
    { key: 'name_attribute', label: 'Name attribute', placeholder: 'displayName' },
  ],
}

const emptyDraft = (protocol: Provider['protocol']): Draft => ({
  name: '', protocol, enabled: true, config: {}, domains: '', role_claim: protocol === 'oidc' ? 'groups' : '',
  role_mappings: [], default_role: 'viewer', auto_provision: true, sync_roles: true, enforce: false,
})

const toDraft = (p: Provider): Draft => ({
  ...p,
  config: Object.fromEntries(Object.entries(p.config).filter(([, v]) => typeof v === 'string')) as Record<string, string>,
  domains: p.email_domains.join(', '),
})

async function detail(res: Response): Promise<string> {
  if (res.status === 403) return 'Only a workspace owner can manage single sign-on.'
  try {
    const body = await res.json()
    return typeof body.detail === 'string' ? body.detail : res.statusText
  } catch {
    return res.statusText
  }
}

function CopyRow({ label, value }: { label: string; value?: string }) {
  if (!value) return null
  return (
    <div className="sso-copy-row">
      <span>{label}</span>
      <code>{value}</code>
      <button type="button" className="ops-refresh-btn" onClick={() => navigator.clipboard?.writeText(value)}>Copy</button>
    </div>
  )
}

export function SsoPanel() {
  const [providers, setProviders] = useState<Provider[]>([])
  const [groups, setGroups] = useState<{ id: string; name: string }[]>([])
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [draft, setDraft] = useState<Draft | null>(null)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    const res = await fetch(`${API_BASE}/api/iam/sso`)
    if (!res.ok) {
      setError(await detail(res))
      return
    }
    setError('')
    setProviders((await res.json()).providers)
    const g = await fetch(`${API_BASE}/api/iam/groups`)
    if (g.ok) setGroups((await g.json()).groups ?? [])
  }, [])

  useEffect(() => { load() }, [load])

  const set = (fields: Partial<Draft>) => setDraft((d) => (d ? { ...d, ...fields } : d))

  // SAML: fill the IdP fields from its metadata XML, or the certificate from a .pem / .cer / .crt file
  const upload = async (e: ChangeEvent<HTMLInputElement>, kind: 'metadata' | 'certificate') => {
    const file = e.target.files?.[0]
    e.target.value = ''   // choosing the same file again still fires
    if (!file) return
    try {
      if (file.size > 1024 * 1024) throw new Error('That file is larger than 1 MB.')
      const bytes = new Uint8Array(await file.arrayBuffer())
      if (kind === 'metadata') {
        const meta = parseSamlMetadata(new TextDecoder().decode(bytes))
        setDraft((d) => (d ? { ...d, config: { ...d.config, ...meta } } : d))
        setNotice(`Read ${file.name}: entity ID, sign-on URL and signing certificate filled in.`)
      } else {
        const pem = certificateFromBytes(bytes)
        setDraft((d) => (d ? { ...d, config: { ...d.config, idp_certificate: pem } } : d))
        setNotice(`Read the certificate from ${file.name}.`)
      }
      setError('')
    } catch (err) {
      setError(`${file.name}: ${err instanceof Error ? err.message : 'could not be read'}`)
    }
  }
  const setMapping = (i: number, fields: Partial<Mapping>) =>
    set({ role_mappings: draft!.role_mappings.map((m, j) => (j === i ? { ...m, ...fields } : m)) })

  const save = async (e: FormEvent) => {
    e.preventDefault()
    if (!draft) return
    setSaving(true)
    setError('')
    const body = {
      name: draft.name, protocol: draft.protocol, enabled: draft.enabled, config: draft.config,
      email_domains: draft.domains.split(/[\s,]+/).filter(Boolean), role_claim: draft.role_claim,
      role_mappings: draft.role_mappings.filter((m) => m.value.trim()), default_role: draft.default_role,
      auto_provision: draft.auto_provision, sync_roles: draft.sync_roles, enforce: draft.enforce,
    }
    const res = await fetch(`${API_BASE}/api/iam/sso${draft.id ? `/${draft.id}` : ''}`, {
      method: draft.id ? 'PUT' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    setSaving(false)
    if (!res.ok) {
      setError(await detail(res))
      return
    }
    const saved: Provider = await res.json()
    setNotice(draft.id ? `Saved ${saved.name}.` : `Added ${saved.name}. Register the URLs below at your identity provider, then test it.`)
    setDraft(null)
    load()
  }

  const test = async (p: Provider) => {
    setNotice('')
    const res = await fetch(`${API_BASE}/api/iam/sso/${p.id}/test`, { method: 'POST' })
    const body = res.ok ? await res.json() : { ok: false, detail: await detail(res) }
    if (body.ok) {
      setError('')
      setNotice(`${p.name}: ${body.detail}`)
    } else {
      setError(`${p.name}: ${body.detail}`)
    }
  }

  const remove = async (p: Provider) => {
    if (!window.confirm(`Remove ${p.name}? People who signed in with it are signed out.`)) return
    const res = await fetch(`${API_BASE}/api/iam/sso/${p.id}`, { method: 'DELETE' })
    if (!res.ok) setError(await detail(res))
    else load()
  }

  return (
    <div className="ops-panel">
      <div className="ops-toolbar">
        <div className="ops-toolbar-left">
          <span className="ops-panel-title">Single sign-on</span>
          <span className="ops-count-badge">{providers.length} provider{providers.length === 1 ? '' : 's'}</span>
          <HelpLink page="11-settings-admin" section="single-sign-on-sso" label="Setting up SSO" />
        </div>
        <div className="ops-toolbar-right">
          {!draft && (
            <>
              <button type="button" className="ops-refresh-btn" onClick={() => setDraft(emptyDraft('oidc'))}>+ OIDC provider</button>
              <button type="button" className="ops-refresh-btn" onClick={() => setDraft(emptyDraft('saml'))}>+ SAML provider</button>
            </>
          )}
        </div>
      </div>

      <div className="sso-body">
        {error && <div className="sso-error" role="alert">{error}</div>}
        {notice && <div className="sso-notice" role="status">{notice}</div>}

        {draft && (
          <form className="sso-card" onSubmit={save}>
            <h3>{draft.id ? `Edit ${draft.name}` : `New ${draft.protocol.toUpperCase()} provider`}</h3>
            {draft.protocol === 'saml' && (
              <div className="sso-upload">
                <label className="ops-refresh-btn sso-upload-btn">
                  Upload IdP metadata (.xml)
                  <input type="file" accept=".xml,application/xml,text/xml,application/samlmetadata+xml" hidden
                    onChange={(e) => upload(e, 'metadata')} />
                </label>
                <small>
                  Download it from your IdP (Okta: "Identity Provider metadata"; Entra ID: "Federation Metadata XML";
                  ADFS: /FederationMetadata/2007-06/FederationMetadata.xml). It fills the three fields below.
                </small>
              </div>
            )}
            <label className="sso-field">
              <span>Name (shown on the sign-in screen)</span>
              <input className="field-input" value={draft.name} onChange={(e) => set({ name: e.target.value })}
                placeholder="Okta, Entra ID, Google Workspace…" required />
            </label>
            {FIELDS[draft.protocol].map((f) => {
              // The certificate field holds its own upload <label>, which can't sit inside another label
              const Wrap = f.multiline ? 'div' : 'label'
              return (
              <Wrap key={f.key} className="sso-field">
                <span>{f.label}</span>
                {f.multiline ? (
                  <textarea className="field-input code-font" rows={5} aria-label={f.label} value={draft.config[f.key] ?? ''}
                    placeholder={f.placeholder} onChange={(e) => set({ config: { ...draft.config, [f.key]: e.target.value } })} />
                ) : (
                  <input className={`field-input${f.secret ? '' : ' code-font'}`} type={f.secret ? 'password' : 'text'}
                    value={draft.config[f.key] ?? ''} autoComplete="off"
                    placeholder={f.secret && draft.id ? 'Leave empty to keep the saved secret' : f.placeholder}
                    onChange={(e) => set({ config: { ...draft.config, [f.key]: e.target.value } })} />
                )}
                {f.key === 'idp_certificate' && (
                  <span className="sso-upload">
                    <label className="ops-link-btn sso-upload-btn">
                      Upload certificate (.pem, .cer, .crt)
                      <input type="file" accept=".pem,.cer,.crt,.der" hidden onChange={(e) => upload(e, 'certificate')} />
                    </label>
                  </span>
                )}
                {f.hint && <small>{f.hint}</small>}
              </Wrap>
              )
            })}
            <label className="sso-field">
              <span>Email domains</span>
              <input className="field-input code-font" value={draft.domains} onChange={(e) => set({ domains: e.target.value })}
                placeholder="acme.com, acme.co.uk" />
              <small>Only these emails may sign in through this provider, and they are offered it on the sign-in screen.</small>
            </label>

            <h4>Role mapping</h4>
            <label className="sso-field">
              <span>{draft.protocol === 'oidc' ? 'Claim with groups or roles' : 'Attribute with groups or roles'}</span>
              <input className="field-input code-font" value={draft.role_claim} onChange={(e) => set({ role_claim: e.target.value })}
                placeholder={draft.protocol === 'oidc' ? 'groups (Keycloak: realm_access.roles)' : 'http://schemas.microsoft.com/ws/2008/06/identity/claims/groups'} />
            </label>
            <div className="sso-mappings">
              {draft.role_mappings.map((m, i) => (
                <div key={i} className="sso-mapping">
                  <input className="field-input code-font" value={m.value} placeholder="IdP value, e.g. pipesets-admins"
                    onChange={(e) => setMapping(i, { value: e.target.value })} />
                  <select className="field-select" value={m.role} onChange={(e) => setMapping(i, { role: e.target.value as Role | '' })}>
                    <option value="">No role change</option>
                    <option value="owner">Owner</option>
                    <option value="editor">Editor</option>
                    <option value="viewer">Viewer</option>
                  </select>
                  <select className="field-select" value={m.group_id} onChange={(e) => setMapping(i, { group_id: e.target.value })}>
                    <option value="">No group</option>
                    {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
                  </select>
                  <button type="button" className="ops-link-btn" aria-label="Remove mapping"
                    onClick={() => set({ role_mappings: draft.role_mappings.filter((_, j) => j !== i) })}>Remove</button>
                </div>
              ))}
              <button type="button" className="ops-link-btn"
                onClick={() => set({ role_mappings: [...draft.role_mappings, { value: '', role: 'editor', group_id: '' }] })}>
                + Add mapping
              </button>
            </div>
            <label className="sso-field">
              <span>When no mapping matches</span>
              <select className="field-select" value={draft.default_role} onChange={(e) => set({ default_role: e.target.value as Role | '' })}>
                <option value="viewer">Sign in as viewer</option>
                <option value="editor">Sign in as editor</option>
                <option value="">Refuse the sign-in</option>
              </select>
              <small>The highest mapped role wins. Mapped groups grant the access rules (ACLs) set on them.</small>
            </label>

            <label className="sso-check">
              <input type="checkbox" checked={draft.auto_provision} onChange={(e) => set({ auto_provision: e.target.checked })} />
              Create accounts on first sign-in (otherwise an owner must add people under Members first)
            </label>
            <label className="sso-check">
              <input type="checkbox" checked={draft.sync_roles} onChange={(e) => set({ sync_roles: e.target.checked })} />
              Re-apply roles and mapped groups at every sign-in (the last owner is never demoted)
            </label>
            <label className="sso-check">
              <input type="checkbox" checked={draft.enforce} onChange={(e) => set({ enforce: e.target.checked })} />
              Require SSO for this workspace: members can't use passwords here (owners still can, as a fallback)
            </label>
            <label className="sso-check">
              <input type="checkbox" checked={draft.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
              Enabled
            </label>

            <div className="sso-actions">
              <button type="submit" className="save-btn" disabled={saving}>{saving ? 'Saving…' : draft.id ? 'Save' : 'Add provider'}</button>
              <button type="button" className="ops-link-btn" onClick={() => setDraft(null)}>Cancel</button>
            </div>
          </form>
        )}

        {!draft && providers.length === 0 && !error && (
          <div className="ops-empty">
            No identity providers yet. Add Okta, Microsoft Entra ID, Google Workspace, Keycloak, Auth0 or any other OIDC or
            SAML 2.0 provider so people sign in with their work account.
          </div>
        )}

        {!draft && providers.map((p) => (
          <div key={p.id} className="sso-card">
            <div className="sso-card-head">
              <h3>{p.name}</h3>
              <span className="ops-count-badge">{p.protocol.toUpperCase()}</span>
              {!p.enabled && <span className="ops-count-badge">Off</span>}
              {p.enforce && <span className="ops-count-badge">Required</span>}
              <div className="sso-card-buttons">
                <button type="button" className="ops-refresh-btn" onClick={() => test(p)}>Test</button>
                <button type="button" className="ops-refresh-btn" onClick={() => setDraft(toDraft(p))}>Edit</button>
                <button type="button" className="ops-danger-btn ops-danger-btn--sm" onClick={() => remove(p)}>Remove</button>
              </div>
            </div>
            <div className="sso-meta">
              {p.email_domains.length ? p.email_domains.join(', ') : 'Any email domain'} ·{' '}
              {p.role_mappings.length} role mapping{p.role_mappings.length === 1 ? '' : 's'} · unmapped:{' '}
              {p.default_role || 'refused'}
            </div>
            <CopyRow label="Redirect URI" value={p.redirect_uri} />
            <CopyRow label="SP entity ID / metadata" value={p.sp_entity_id} />
            <CopyRow label="ACS URL" value={p.acs_url} />
          </div>
        ))}
      </div>
    </div>
  )
}
