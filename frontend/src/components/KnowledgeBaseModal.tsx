import { useState, useRef } from 'react'
import { API_BASE } from '../types'
import type { KnowledgeBaseRecord } from '../types'

interface Props {
  kb?: KnowledgeBaseRecord
  onSaved: (kb: KnowledgeBaseRecord) => void
  onClose: () => void
}

const SOURCE_TYPES: { type: 'text' | 'file' | 'web_url'; icon: string; label: string; sub: string }[] = [
  { type: 'text',    icon: '✍️', label: 'Raw Text',    sub: 'Paste policy / docs' },
  { type: 'file',    icon: '📄', label: 'File Upload',  sub: 'PDF, TXT, MD' },
  { type: 'web_url', icon: '🌐', label: 'Web Crawler',  sub: 'URL crawl' },
]

const EMBEDDING_PROVIDERS = [
  { value: 'local',        icon: '💻', label: 'Local (HuggingFace)',     model: 'sentence-transformers/all-MiniLM-L6-v2', keyLabel: 'HuggingFace Token (optional)', keyPlaceholder: 'hf_... (optional)',      needsKey: false },
  { value: 'openai',       icon: '🤖', label: 'OpenAI',                  model: 'text-embedding-3-small',                keyLabel: 'OpenAI API Key',                keyPlaceholder: 'sk-...',                 needsKey: true  },
  { value: 'cohere',       icon: '🟠', label: 'Cohere',                  model: 'embed-english-v3.0',                    keyLabel: 'Cohere API Key',                keyPlaceholder: 'co-...',                 needsKey: true  },
  { value: 'google',       icon: '🌈', label: 'Google Gemini',           model: 'text-embedding-004',                    keyLabel: 'Google API Key',                keyPlaceholder: 'AIza...',                needsKey: true  },
  { value: 'azure_openai', icon: '🔵', label: 'Azure OpenAI',            model: 'text-embedding-3-small',                keyLabel: 'Azure API Key',                 keyPlaceholder: 'your-azure-api-key',     needsKey: true  },
  { value: 'mistral',      icon: '🌊', label: 'Mistral',                 model: 'mistral-embed',                         keyLabel: 'Mistral API Key',               keyPlaceholder: 'your-mistral-key',       needsKey: true  },
  { value: 'ollama',       icon: '🦙', label: 'Ollama (local)',          model: 'nomic-embed-text',                      keyLabel: 'Ollama Base URL',               keyPlaceholder: 'http://localhost:11434', needsKey: false },
  { value: 'llamacpp',     icon: '🦙', label: 'llama.cpp (local)',       model: 'default',                               keyLabel: 'llama-server Base URL',         keyPlaceholder: 'http://localhost:8080',  needsKey: false },
  { value: 'bedrock',      icon: '☁️', label: 'AWS Bedrock',             model: 'amazon.titan-embed-text-v2:0',          keyLabel: 'AWS Access Key ID',             keyPlaceholder: 'AKIA...',                needsKey: true  },
  { value: 'voyage',       icon: '🚀', label: 'Voyage AI',               model: 'voyage-3',                              keyLabel: 'Voyage AI API Key',             keyPlaceholder: 'pa-...',                 needsKey: true  },
  { value: 'nomic',        icon: '🗺️', label: 'Nomic',                   model: 'nomic-embed-text-v1.5',                 keyLabel: 'Nomic API Key',                 keyPlaceholder: 'nk-...',                 needsKey: true  },
  { value: 'anthropic',    icon: '🤝', label: 'Anthropic (via Voyage)',  model: 'voyage-3',                              keyLabel: 'Voyage AI API Key',             keyPlaceholder: 'pa-...',                 needsKey: true  },
]

export function KnowledgeBaseModal({ kb, onSaved, onClose }: Props) {
  const isEdit = !!kb

  const [name, setName] = useState(kb?.name ?? 'Company Knowledge Base')
  const [icon, setIcon] = useState(kb?.icon ?? '📚')
  const [description, setDescription] = useState(kb?.description ?? 'Indexed documentation and guidelines for RAG agents.')
  const [sourceType, setSourceType] = useState<'text' | 'file' | 'web_url'>('text')

  // Content sources
  const [rawText, setRawText] = useState(
    'Company Support & Refund Policy:\n1. All enterprise subscriptions include 24/7 dedicated support.\n2. Invoices are billed annually or monthly with a 30-day money-back guarantee.\n3. SLA response time for critical incidents (P0) is under 15 minutes.'
  )
  const [webUrl, setWebUrl] = useState('https://example.com/docs')
  const [file, setFile] = useState<File | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Embedding config
  const [embeddingProvider, setEmbeddingProvider] = useState('local')
  const [embeddingModel, setEmbeddingModel] = useState('sentence-transformers/all-MiniLM-L6-v2')
  const [apiKey, setApiKey] = useState('')
  const [chunkSize, setChunkSize] = useState(500)
  const [chunkOverlap, setChunkOverlap] = useState(50)

  const [isSaving, setIsSaving] = useState(false)
  const [errorMsg, setErrorMsg] = useState('')

  const currentEP = EMBEDDING_PROVIDERS.find(p => p.value === embeddingProvider)!

  const handleProviderChange = (value: string) => {
    const ep = EMBEDDING_PROVIDERS.find(p => p.value === value)!
    setEmbeddingProvider(value)
    setEmbeddingModel(ep.model)
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) { setErrorMsg('Knowledge Base name is required.'); return }
    setIsSaving(true)
    setErrorMsg('')
    try {
      let res: Response
      if (sourceType === 'file') {
        if (!file) throw new Error('Please select a file to upload.')
        const formData = new FormData()
        formData.append('name', name.trim())
        formData.append('icon', icon.trim() || '📚')
        formData.append('description', description.trim())
        formData.append('embedding_provider', embeddingProvider)
        formData.append('embedding_model', embeddingModel)
        formData.append('api_key', apiKey)
        formData.append('chunk_size', String(chunkSize))
        formData.append('chunk_overlap', String(chunkOverlap))
        formData.append('file', file)
        res = await fetch(`${API_BASE}/api/knowledge-bases/upload`, { method: 'POST', body: formData })
      } else {
        const payload = {
          name: name.trim(), icon: icon.trim() || '📚', description: description.trim(),
          source_type: sourceType, content: sourceType === 'text' ? rawText : '',
          url: sourceType === 'web_url' ? webUrl : '',
          embedding_provider: embeddingProvider, embedding_model: embeddingModel,
          api_key: apiKey, chunk_size: chunkSize, chunk_overlap: chunkOverlap,
        }
        res = await fetch(`${API_BASE}/api/knowledge-bases`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      }
      if (!res.ok) { const err = await res.json(); throw new Error(err.detail || 'Failed to create Knowledge Base') }
      const saved: KnowledgeBaseRecord = await res.json()
      onSaved(saved)
      onClose()
    } catch (err: any) {
      setErrorMsg(err.message || 'Error indexing knowledge base')
    } finally {
      setIsSaving(false)
    }
  }

  const currentSource = SOURCE_TYPES.find(s => s.type === sourceType)!

  return (
    <div className="modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="conn-modal-shell">

        {/* ── Header ── */}
        <div className="conn-modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 20 }}>{icon}</span>
            <div>
              <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: '#0f172a' }}>
                {isEdit ? 'Edit Knowledge Base' : '+ Create Knowledge Base'}
              </h3>
              <p style={{ margin: 0, fontSize: 11, color: '#64748b', marginTop: 1 }}>
                {currentSource.label} · {currentSource.sub}
              </p>
            </div>
          </div>
          <button type="button" className="modal-close-btn" onClick={onClose}>✕</button>
        </div>

        {/* ── Two-column body ── */}
        <div className="conn-modal-body">

          {/* LEFT — source type nav */}
          <nav className="conn-provider-nav">
            <p className="conn-nav-label">Source</p>
            {SOURCE_TYPES.map(s => (
              <button
                key={s.type}
                type="button"
                className={`conn-nav-item ${sourceType === s.type ? 'active' : ''}`}
                onClick={() => setSourceType(s.type)}
              >
                <span className="conn-nav-icon">{s.icon}</span>
                <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                  <span className="conn-nav-name">{s.label}</span>
                  <span style={{ fontSize: 10, color: '#94a3b8', lineHeight: 1.2, marginTop: 1 }}>{s.sub}</span>
                </div>
              </button>
            ))}

            <div style={{ borderTop: '1px solid #e9eef5', margin: '12px 0 10px' }} />
            <p className="conn-nav-label">Embedding</p>
            {EMBEDDING_PROVIDERS.map(ep => (
              <button
                key={ep.value}
                type="button"
                className={`conn-nav-item ${embeddingProvider === ep.value ? 'active' : ''}`}
                onClick={() => handleProviderChange(ep.value)}
              >
                <span className="conn-nav-icon">{ep.icon}</span>
                <span className="conn-nav-name" style={{ fontSize: 11 }}>{ep.label}</span>
                {!ep.needsKey && <span className="conn-nav-tag">Free</span>}
              </button>
            ))}
          </nav>

          {/* RIGHT — config form */}
          <form className="conn-config-panel" onSubmit={handleSave}>
            <div className="conn-config-scroll">

              {errorMsg && <div className="ct-save-error" style={{ marginBottom: 10 }}>{errorMsg}</div>}

              {/* Identity */}
              <div className="conn-section-label">Identity</div>
              <div className="form-row" style={{ gap: 10, marginBottom: 10 }}>
                <div className="form-group" style={{ flex: '0 0 56px' }}>
                  <label className="field-label">Icon</label>
                  <input type="text" className="field-input ct-icon-input" value={icon} onChange={(e) => setIcon(e.target.value)} maxLength={4} />
                </div>
                <div className="form-group flex-1">
                  <label className="field-label">Knowledge Base Name *</label>
                  <input type="text" className="field-input" placeholder="e.g. HR Policy, API Documentation, Incident Playbook..." value={name} onChange={(e) => setName(e.target.value)} required />
                </div>
              </div>
              <div className="form-group" style={{ marginBottom: 14 }}>
                <label className="field-label">Description</label>
                <input type="text" className="field-input" placeholder="What topics are covered in this knowledge base?" value={description} onChange={(e) => setDescription(e.target.value)} />
              </div>

              {/* Source content */}
              <div className="conn-section-label">Content</div>

              {sourceType === 'text' && (
                <div className="form-group">
                  <label className="field-label">Document Text *</label>
                  <textarea
                    rows={7}
                    className="field-textarea font-mono"
                    style={{ fontSize: 11 }}
                    placeholder="Paste documentation, articles, FAQs, or policies..."
                    value={rawText}
                    onChange={(e) => setRawText(e.target.value)}
                    required
                  />
                </div>
              )}

              {sourceType === 'file' && (
                <div className="form-group">
                  <label className="field-label">Upload File (PDF, TXT, MD) *</label>
                  <div
                    className="kb-drop-zone"
                    onClick={() => fileInputRef.current?.click()}
                    style={{ background: file ? '#eff6ff' : '#f8fafc', borderColor: file ? '#93c5fd' : '#cbd5e1' }}
                  >
                    <span style={{ fontSize: 28 }}>📄</span>
                    <p style={{ margin: '6px 0 0', fontSize: 12, fontWeight: 600, color: '#334155' }}>
                      {file ? file.name : 'Click to select PDF or Document'}
                    </p>
                    <span className="field-hint">{file ? `${(file.size / 1024).toFixed(1)} KB` : 'Supports .pdf, .txt, .md, .json'}</span>
                    <input ref={fileInputRef} type="file" accept=".pdf,.txt,.md,.json" style={{ display: 'none' }}
                      onChange={(e) => e.target.files?.[0] && setFile(e.target.files[0])} />
                  </div>
                </div>
              )}

              {sourceType === 'web_url' && (
                <div className="form-group">
                  <label className="field-label">Target URL *</label>
                  <input type="url" className="field-input font-mono" placeholder="https://docs.mycompany.com/handbook" value={webUrl} onChange={(e) => setWebUrl(e.target.value)} required />
                </div>
              )}

              {/* Embedding config */}
              <div className="conn-section-label" style={{ marginTop: 14 }}>Embedding Config</div>
              <div className="kb-provider-banner">
                <span style={{ fontSize: 16 }}>{currentEP.icon}</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: '#0f172a' }}>{currentEP.label}</div>
                  <div style={{ fontSize: 11, color: '#64748b' }}>{currentEP.model}</div>
                </div>
                {!currentEP.needsKey && <span className="conn-nav-tag" style={{ alignSelf: 'center' }}>No key needed</span>}
              </div>

              <div className="form-group" style={{ marginTop: 10 }}>
                <label className="field-label">Model</label>
                <input type="text" className="field-input font-mono" value={embeddingModel} onChange={(e) => setEmbeddingModel(e.target.value)} />
              </div>

              {currentEP.needsKey && (
                <div className="form-group">
                  <label className="field-label">{currentEP.keyLabel} *</label>
                  <input
                    type={embeddingProvider === 'ollama' ? 'text' : 'password'}
                    className="field-input font-mono"
                    placeholder={currentEP.keyPlaceholder}
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    required
                  />
                </div>
              )}

              {/* Chunking */}
              <div className="conn-section-label" style={{ marginTop: 14 }}>Chunking</div>
              <div className="form-row" style={{ gap: 10 }}>
                <div className="form-group flex-1">
                  <label className="field-label">Chunk Size</label>
                  <input type="number" className="field-input font-mono" value={chunkSize} onChange={(e) => setChunkSize(Number(e.target.value))} />
                </div>
                <div className="form-group flex-1">
                  <label className="field-label">Overlap</label>
                  <input type="number" className="field-input font-mono" value={chunkOverlap} onChange={(e) => setChunkOverlap(Number(e.target.value))} />
                </div>
              </div>

            </div>{/* /conn-config-scroll */}

            <div className="conn-modal-footer">
              <button type="button" className="cancel-btn" onClick={onClose} disabled={isSaving}>Cancel</button>
              <button type="submit" className="save-btn" disabled={isSaving}>
                {isSaving ? '⚡ Ingesting & Embedding...' : 'Index Knowledge Base'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}
