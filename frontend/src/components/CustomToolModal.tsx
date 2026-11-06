import { useState, useRef, useCallback, useEffect, useMemo } from 'react'
import { API_BASE } from '../types'
import { describeParams } from '../utils/toolParams'
import type { ParamSchema } from '../utils/toolParams'
import { HelpLink } from './docs/HelpLink'

export interface CustomToolRecord {
  id: string
  name: string
  icon: string
  description: string
  code: string
  config_keys: string[]
  requirements?: string[]
  created_at: string
  updated_at: string
  version?: number
  source?: 'ui' | 'sdk'
  read_only?: boolean              // deployed from the SDK: change it in code, or fork it
  parameters?: JsonSchema | null   // what the model calls it with
  legacy?: boolean                 // run(input_text, config): one input string
}

type JsonSchema = ParamSchema

interface Signature {
  ok: boolean
  error?: string
  legacy?: boolean
  entrypoint?: string
  parameters?: JsonSchema
}

interface VersionRow {
  version: number
  source: string
  note: string | null
  created_at: string
  created_by: string | null
}

interface Props {
  tool?: CustomToolRecord          // undefined = create mode
  initialDraft?: {
    name?: string
    icon?: string
    description?: string
    code?: string
    config_keys?: string[]
    packages?: string[]
  }
  onSaved: (tool: CustomToolRecord) => void
  onClose: () => void
}

/** FastAPI error body → message (422 validation errors arrive as a list). */
function errorDetail(data: any): string {
  const d = data?.detail
  if (Array.isArray(d)) return d.map((e) => String(e?.msg ?? e).replace(/^Value error, /, '')).join('; ')
  return typeof d === 'string' ? d : 'Request failed'
}

// Typed: the parameters become the function the model calls. Legacy run(input_text, config) still works.
const DEFAULT_CODE = `from pipesets import tool


@tool(description="Reverse a piece of text")
def reverse_text(text: str, shout: bool = False, *, config) -> str:
    """Reverse the text.

    Args:
        text: The text to reverse
        shout: Return it in upper case
    """
    # config: the values of the keys in the Config Keys tab (secrets decrypted)
    result = text.strip()[::-1]
    return result.upper() if shout else result
`



export function CustomToolModal({ tool, initialDraft, onSaved, onClose }: Props) {
  const isEdit = !!tool
  const readOnly = !!tool?.read_only

  const [name, setName] = useState(tool?.name ?? initialDraft?.name ?? '')
  const [icon, setIcon] = useState(tool?.icon ?? initialDraft?.icon ?? '🔧')
  const [description, setDescription] = useState(tool?.description ?? initialDraft?.description ?? '')
  const [code, setCode] = useState(tool?.code ?? initialDraft?.code ?? DEFAULT_CODE)
  const [configKeys, setConfigKeys] = useState<string[]>(tool?.config_keys ?? initialDraft?.config_keys ?? [])
  const [newKey, setNewKey] = useState('')

  // pip specs, one per line; installed into the tool's own sandbox environment on first run
  const [packages, setPackages] = useState((tool?.requirements ?? initialDraft?.packages ?? []).join('\n'))
  const requirements = useMemo(() => packages.split(/[\s,]+/).map((p) => p.trim()).filter(Boolean), [packages])

  // The parameters the model will see, read from the code by the server (nothing runs)
  const [signature, setSignature] = useState<Signature | null>(null)
  useEffect(() => {
    const t = setTimeout(() => {
      fetch(`${API_BASE}/api/custom-tools/signature`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code }),
      }).then((r) => (r.ok ? r.json() : null)).then(setSignature).catch(() => setSignature(null))
    }, 400)
    return () => clearTimeout(t)
  }, [code])
  const typed = !!signature?.ok && !signature.legacy

  // Version history (edit mode)
  const [versions, setVersions] = useState<VersionRow[]>([])
  const [currentVersion, setCurrentVersion] = useState(tool?.version ?? 1)
  const [viewing, setViewing] = useState<{ version: number; code: string } | null>(null)
  const loadVersions = useCallback(async () => {
    if (!tool) return
    const r = await fetch(`${API_BASE}/api/custom-tools/${tool.id}/versions`).catch(() => null)
    if (r?.ok) {
      const data = await r.json()
      setVersions(data.versions)
      setCurrentVersion(data.current)
    }
  }, [tool])

  // Test runner state
  const [testInput, setTestInput] = useState('')
  const [testArgs, setTestArgs] = useState('{}')
  const [testConfig, setTestConfig] = useState('{}')
  const [testOutput, setTestOutput] = useState('')
  const [isTesting, setIsTesting] = useState(false)

  // Save state
  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState('')

  // Active tab
  const [tab, setTab] = useState<'code' | 'config' | 'packages' | 'test' | 'versions'>('code')
  useEffect(() => { if (tab === 'versions') void loadVersions() }, [tab, loadVersions])

  const fileInputRef = useRef<HTMLInputElement>(null)

  // ── Config key management ───────────────────────────────────────────────────
  const addKey = () => {
    const k = newKey.trim().replace(/\s+/g, '_').toLowerCase()
    if (k && !configKeys.includes(k)) {
      setConfigKeys((prev) => [...prev, k])
    }
    setNewKey('')
  }

  const removeKey = (k: string) => setConfigKeys((prev) => prev.filter((x) => x !== k))

  // ── Test runner ─────────────────────────────────────────────────────────────
  const handleTest = useCallback(async () => {
    setIsTesting(true)
    setTestOutput('')
    let parsedConfig: Record<string, any> = {}
    try { parsedConfig = JSON.parse(testConfig) } catch { /* leave empty */ }
    let args: Record<string, any> | undefined
    if (typed) {
      try { args = JSON.parse(testArgs) } catch {
        setTestOutput('❌ Arguments are not valid JSON')
        setIsTesting(false)
        return
      }
    }

    try {
      const res = await fetch(`${API_BASE}/api/custom-tools/execute-code`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, input_text: testInput, args, config: parsedConfig, requirements }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(errorDetail(data))
      setTestOutput(data.success ? data.output : `❌ ${data.output}`)
    } catch (e: any) {
      setTestOutput(`❌ ${e.message}`)
    } finally {
      setIsTesting(false)
    }
  }, [code, testInput, testArgs, testConfig, requirements, typed])

  // ── Versions: rollback, fork ────────────────────────────────────────────────
  const post = useCallback(async (path: string, body?: unknown) => {
    setSaveError('')
    try {
      const res = await fetch(`${API_BASE}/api/custom-tools/${tool!.id}${path}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined,
      })
      if (!res.ok) throw new Error(errorDetail(await res.json().catch(() => ({}))))
      onSaved(await res.json())
    } catch (e: any) {
      setSaveError(e.message)
    }
  }, [tool, onSaved])

  const showVersion = useCallback(async (version: number) => {
    const r = await fetch(`${API_BASE}/api/custom-tools/${tool!.id}/versions/${version}`).catch(() => null)
    if (r?.ok) setViewing({ version, code: (await r.json()).code })
  }, [tool])

  // ── File upload ─────────────────────────────────────────────────────────────
  const handleFileUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const text = await file.text()
    setCode(text)
    if (!name) setName(file.name.replace('.py', '').replace(/_/g, ' '))
    setTab('code')
  }, [name])

  // ── Save ────────────────────────────────────────────────────────────────────
  const handleSave = useCallback(async () => {
    if (!name.trim()) { setSaveError('Name is required.'); return }
    if (!code.trim()) { setSaveError('Code is required.'); return }
    setSaveError('')
    setIsSaving(true)

    const body = { name: name.trim(), icon, description, code, config_keys: configKeys, requirements }
    const url = isEdit
      ? `${API_BASE}/api/custom-tools/${tool!.id}`
      : `${API_BASE}/api/custom-tools`
    const method = isEdit ? 'PUT' : 'POST'

    try {
      const res = await fetch(url, {
        method, headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) throw new Error(errorDetail(await res.json().catch(() => ({}))))
      const saved: CustomToolRecord = await res.json()
      onSaved(saved)
    } catch (e: any) {
      setSaveError(`Save failed: ${e.message}`)
    } finally {
      setIsSaving(false)
    }
  }, [name, icon, description, code, configKeys, requirements, isEdit, tool, onSaved])

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div className="modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="modal-card custom-tool-modal">
        {/* Header */}
        <div className="modal-header">
          <h3>
            {isEdit ? `${readOnly ? '' : 'Edit Tool: '}${tool!.name}` : 'New Custom Tool'}
            <HelpLink page="03-tools" section="custom-tools" label="Writing a custom tool" />
            {isEdit && <span className="ct-version-badge">v{currentVersion}</span>}
            {readOnly && <span className="ct-sdk-badge" title="Change it in code and run `pipesets tool deploy`">Deployed from SDK</span>}
          </h3>
          <button type="button" className="modal-close-btn" onClick={onClose}>✕</button>
        </div>

        {/* Top meta row */}
        <div className="custom-tool-meta-row">
          <div className="form-group" style={{ flex: '0 0 48px' }}>
            <label className="field-label">Icon</label>
            <input
              type="text"
              className="field-input ct-icon-input"
              value={icon}
              onChange={(e) => setIcon(e.target.value)}
              maxLength={4}
            />
          </div>
          <div className="form-group" style={{ flex: 1 }}>
            <label className="field-label">Tool Name *</label>
            <input
              type="text"
              className="field-input"
              placeholder="e.g. My Custom Tool"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="form-group" style={{ flex: 1 }}>
            <label className="field-label">Description</label>
            <input
              type="text"
              className="field-input"
              placeholder="One line — shown on the drag card"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
        </div>

        {/* Tab bar */}
        <div className="custom-tool-tabs">
          {(['code', 'config', 'packages', 'test', ...(isEdit ? ['versions' as const] : [])] as const).map((t) => (
            <button
              key={t}
              type="button"
              className={`ct-tab${tab === t ? ' active' : ''}`}
              onClick={() => setTab(t)}
            >
              {t === 'code' && 'Code'}
              {t === 'config' && 'Config Keys'}
              {t === 'packages' && 'Packages'}
              {t === 'test' && 'Test'}
              {t === 'versions' && 'Versions'}
            </button>
          ))}
          <div className="ct-tab-spacer" />
          <button
            type="button"
            className="ct-upload-btn"
            title="Upload .py file from VS Code"
            onClick={() => fileInputRef.current?.click()}
          >
            ↑ Upload .py
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".py"
            style={{ display: 'none' }}
            onChange={handleFileUpload}
          />
        </div>

        {/* ── Code tab ── */}
        {tab === 'code' && (
          <div className="ct-tab-body">
            <div className="ct-code-hint">
              Define one <code>@tool</code> function with typed parameters — the model calls it with real arguments — or
              the older <code>def run(input_text: str, config: dict) -&gt; str</code>, which gets one input string.
            </div>
            {readOnly && (
              <div className="ct-readonly-note">
                Deployed with <code>pipesets tool deploy</code>: change it in its repository and redeploy, or fork it to
                edit a copy here.
              </div>
            )}
            <textarea
              className="ct-code-editor"
              value={code}
              readOnly={readOnly}
              onChange={(e) => setCode(e.target.value)}
              spellCheck={false}
              rows={18}
              wrap="off"
            />
            <div className={`ct-signature${signature && !signature.ok ? ' ct-signature--error' : ''}`} aria-live="polite">
              {!signature ? null : !signature.ok ? `⚠ ${signature.error}` : signature.legacy
                ? 'The model sends one input string (legacy run).'
                : (
                  <>
                    <span className="field-label">The model calls <code>{signature.entrypoint}</code> with</span>
                    <ul>{describeParams(signature.parameters).map((line) => <li key={line}><code>{line}</code></li>)}</ul>
                  </>
                )}
            </div>
          </div>
        )}

        {/* ── Config Keys tab ── */}
        {tab === 'config' && (
          <div className="ct-tab-body">
            <p className="field-hint" style={{ marginBottom: 10 }}>
              Config keys become fields in the Tool Config Panel on the canvas.
              The agent passes them as the <code>config</code> dict to your <code>run()</code> function.
            </p>
            <div className="ct-key-add-row">
              <input
                type="text"
                className="field-input"
                placeholder="e.g. api_key"
                value={newKey}
                onChange={(e) => setNewKey(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && addKey()}
              />
              <button type="button" className="ct-add-key-btn" onClick={addKey}>+ Add</button>
            </div>
            <div className="ct-key-list">
              {configKeys.length === 0 && (
                <p className="field-hint">No config keys yet. Keys like <code>api_key</code>, <code>job_id</code> appear as input fields on the canvas.</p>
              )}
              {configKeys.map((k) => (
                <div key={k} className="ct-key-row">
                  <code className="ct-key-name">{k}</code>
                  <span className="field-hint ct-key-desc">config["{k}"]</span>
                  <button
                    type="button"
                    className="ct-key-remove"
                    onClick={() => removeKey(k)}
                  >✕</button>
                </div>
              ))}
            </div>
            {configKeys.length > 0 && (
              <div className="ct-config-preview">
                <span className="field-label">Preview — what your code receives:</span>
                <pre className="ct-preview-code">
{`config = {
${configKeys.map((k) => `    "${k}": "...",`).join('\n')}
}`}
                </pre>
              </div>
            )}
          </div>
        )}

        {/* ── Packages tab ── */}
        {tab === 'packages' && (
          <div className="ct-tab-body">
            <p className="field-hint" style={{ marginBottom: 10 }}>
              Python packages this tool needs, one per line (e.g. <code>requests</code> or <code>httpx&gt;=0.27</code>).
              They're installed into the tool's own sandbox environment on its first run — not into the
              backend — and reused after that, so the first run takes longer.
            </p>
            <textarea
              className="ct-package-input"
              placeholder={'requests\nhttpx>=0.27\nboto3'}
              value={packages}
              onChange={(e) => setPackages(e.target.value)}
              rows={4}
            />
          </div>
        )}

        {/* ── Test tab ── */}
        {tab === 'test' && (
          <div className="ct-tab-body">
            <p className="field-hint" style={{ marginBottom: 10 }}>
              Test your code before saving. Runs in the sandbox with the requirements above.
            </p>
            {typed ? (
              <div className="form-group">
                <label className="field-label">arguments (JSON) — what the model would send</label>
                <textarea
                  className="ct-package-input"
                  placeholder={JSON.stringify(Object.fromEntries((signature?.parameters?.required ?? []).map((k) => [k, '…'])))}
                  value={testArgs}
                  onChange={(e) => setTestArgs(e.target.value)}
                  rows={3}
                />
              </div>
            ) : (
              <div className="form-group">
                <label className="field-label">input_text</label>
                <input
                  type="text"
                  className="field-input"
                  placeholder="The input text your tool will receive"
                  value={testInput}
                  onChange={(e) => setTestInput(e.target.value)}
                />
              </div>
            )}
            <div className="form-group">
              <label className="field-label">config (JSON)</label>
              <textarea
                className="ct-package-input"
                placeholder='{"api_key": "test", "job_id": "abc123"}'
                value={testConfig}
                onChange={(e) => setTestConfig(e.target.value)}
                rows={3}
              />
            </div>
            <button
              type="button"
              className={`ct-install-btn${isTesting ? ' installing' : ''}`}
              onClick={handleTest}
              disabled={isTesting}
            >
              {isTesting ? '⏳ Running…' : '▶ Run Test'}
            </button>
            {testOutput && (
              <div className={`ct-test-output${testOutput.startsWith('❌') ? ' ct-test-error' : ''}`}>
                <span className="field-label">Output</span>
                <pre className="ct-install-log">{testOutput}</pre>
              </div>
            )}
          </div>
        )}

        {/* ── Versions tab ── */}
        {tab === 'versions' && (
          <div className="ct-tab-body">
            <p className="field-hint" style={{ marginBottom: 10 }}>
              Every saved change is a version. Nodes use the latest unless they pin one in their config. Rolling back
              saves an earlier version's code as a new version.
            </p>
            <div className="ct-version-list">
              {versions.map((v) => (
                <div key={v.version} className={`ct-version-row${v.version === currentVersion ? ' ct-version-row--current' : ''}`}>
                  <strong>v{v.version}</strong>
                  <span className="field-hint">{new Date(v.created_at + 'Z').toLocaleString()} · {v.created_by ?? '—'} · {v.source}</span>
                  {v.note && <span className="ct-version-note">{v.note}</span>}
                  <span className="ct-tab-spacer" />
                  <button type="button" className="ct-add-key-btn" onClick={() => showVersion(v.version)}>View</button>
                  {v.version !== currentVersion && (
                    <button type="button" className="ct-add-key-btn" onClick={() => post('/rollback', { version: v.version })}>
                      Roll back to this
                    </button>
                  )}
                </div>
              ))}
            </div>
            {viewing && (
              <div className="ct-test-output">
                <span className="field-label">v{viewing.version}</span>
                <pre className="ct-install-log">{viewing.code}</pre>
              </div>
            )}
          </div>
        )}

        {/* Footer */}
        {saveError && <div className="ct-save-error">{saveError}</div>}
        <div className="modal-actions ct-footer">
          <button type="button" className="modal-cancel-btn" onClick={onClose}>{readOnly ? 'Close' : 'Cancel'}</button>
          {readOnly ? (
            <button type="button" className="modal-create-btn" onClick={() => post('/fork')}>Fork to edit</button>
          ) : (
            <button
              type="button"
              className="modal-create-btn"
              onClick={handleSave}
              disabled={isSaving}
            >
              {isSaving ? 'Saving…' : isEdit ? 'Save Changes' : 'Create Tool'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
