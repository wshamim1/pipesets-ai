import { useState } from 'react'
import type { FormEvent } from 'react'
import { saveCustomDocLoader } from '../utils/docLoaders'
import type { DocLoaderDef } from '../utils/docLoaders'

interface Props {
  /** Existing custom loader when editing. */
  loader?: DocLoaderDef
  onSaved: (loader: DocLoaderDef) => void
  onClose: () => void
}

export function CustomDocLoaderModal({ loader, onSaved, onClose }: Props) {
  const isEdit = !!loader
  const [icon, setIcon] = useState(loader?.icon ?? '🧩')
  const [name, setName] = useState(loader?.label ?? '')
  const [description, setDescription] = useState(loader?.desc ?? '')
  const [loaderClass, setLoaderClass] = useState(loader?.loaderClass ?? '')
  const [kwargs, setKwargs] = useState(loader?.loaderKwargs ?? '')
  const [sourceLabel, setSourceLabel] = useState(loader?.sourceLabel ?? 'Source')
  const [placeholder, setPlaceholder] = useState(loader?.placeholder ?? '')
  const [fileBased, setFileBased] = useState(!!loader?.fileBased)
  const [error, setError] = useState('')

  const handleSave = (e: FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return setError('Loader name is required.')
    if (!loaderClass.trim()) return setError('Loader class / import path is required.')
    if (kwargs.trim()) {
      try {
        const parsed = JSON.parse(kwargs)
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error()
      } catch {
        return setError('Constructor kwargs must be a JSON object, e.g. { "encoding": "utf-8" }.')
      }
    }
    onSaved(saveCustomDocLoader({
      type: loader?.type,
      label: name.trim(),
      icon: icon.trim() || '🧩',
      desc: description.trim() || `Custom loader: ${loaderClass.trim()}`,
      sourceLabel: sourceLabel.trim() || 'Source',
      placeholder: placeholder.trim(),
      fileBased,
      loaderClass: loaderClass.trim(),
      loaderKwargs: kwargs.trim(),
    }))
  }

  return (
    <div className="modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="conn-modal-shell" style={{ width: 'min(560px, 96vw)' }}>
        <div className="conn-modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 20 }}>{icon}</span>
            <div>
              <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: '#0f172a' }}>
                {isEdit ? `Edit Loader: ${loader!.label}` : '+ Add Custom Document Loader'}
              </h3>
              <p style={{ margin: 0, fontSize: 11, color: '#64748b', marginTop: 1 }}>
                Register your own loader class so it can be dropped on the canvas
              </p>
            </div>
          </div>
          <button type="button" className="modal-close-btn" onClick={onClose}>✕</button>
        </div>

        <form className="conn-config-panel" onSubmit={handleSave}>
          <div className="conn-config-scroll">
            {error && <div className="ct-save-error" style={{ marginBottom: 10 }}>{error}</div>}

            <div className="conn-section-label">Identity</div>
            <div className="form-row" style={{ gap: 10, marginBottom: 10 }}>
              <div className="form-group" style={{ flex: '0 0 56px' }}>
                <label className="field-label">Icon</label>
                <input type="text" className="field-input ct-icon-input" value={icon} maxLength={4} onChange={(e) => setIcon(e.target.value)} />
              </div>
              <div className="form-group flex-1">
                <label className="field-label">Loader Name *</label>
                <input type="text" className="field-input" placeholder="e.g. Company Wiki Loader" value={name} onChange={(e) => setName(e.target.value)} required />
              </div>
            </div>
            <div className="form-group" style={{ marginBottom: 14 }}>
              <label className="field-label">Description</label>
              <input type="text" className="field-input" placeholder="What does this loader read?" value={description} onChange={(e) => setDescription(e.target.value)} />
            </div>

            <div className="conn-section-label">Implementation</div>
            <div className="form-group" style={{ marginBottom: 10 }}>
              <label className="field-label">Loader Class / Import Path *</label>
              <input type="text" className="field-input font-mono" placeholder="my_package.loaders.CompanyWikiLoader" value={loaderClass} onChange={(e) => setLoaderClass(e.target.value)} required />
              <span className="field-hint">Any LangChain-compatible loader (a BaseLoader subclass with load() / lazy_load()).</span>
            </div>
            <div className="form-group" style={{ marginBottom: 14 }}>
              <label className="field-label">Constructor Kwargs (JSON)</label>
              <textarea rows={3} className="field-textarea font-mono" style={{ fontSize: 11 }}
                placeholder='{ "encoding": "utf-8", "recursive": true }'
                value={kwargs} onChange={(e) => setKwargs(e.target.value)} />
            </div>

            <div className="conn-section-label">Source Input</div>
            <div className="form-row" style={{ gap: 10 }}>
              <div className="form-group flex-1">
                <label className="field-label">Source Label</label>
                <input type="text" className="field-input" placeholder="File Path, URL, Query…" value={sourceLabel} onChange={(e) => setSourceLabel(e.target.value)} />
              </div>
              <div className="form-group flex-1">
                <label className="field-label">Placeholder</label>
                <input type="text" className="field-input font-mono" placeholder="/path/to/file" value={placeholder} onChange={(e) => setPlaceholder(e.target.value)} />
              </div>
            </div>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#334155', marginTop: 4 }}>
              <input type="checkbox" checked={fileBased} onChange={(e) => setFileBased(e.target.checked)} />
              Source is an uploadable file (show upload dropzone)
            </label>
          </div>

          <div className="conn-modal-footer">
            <button type="button" className="cancel-btn" onClick={onClose}>Cancel</button>
            <button type="submit" className="save-btn">{isEdit ? 'Update Loader' : 'Add Loader'}</button>
          </div>
        </form>
      </div>
    </div>
  )
}
