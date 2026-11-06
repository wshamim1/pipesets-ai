import { useState, useEffect, useCallback } from 'react'
import { API_BASE } from '../types'

// ── Types ─────────────────────────────────────────────────────────────────────

export type ExportFormat =
  | 'native_json'
  | 'openapi'
  | 'langchain'
  | 'crewai'
  | 'autogen'
  | 'docker_compose'
  | 'notebook'
  | 'readme'
  | 'skill'

interface FormatMeta {
  id: ExportFormat
  label: string
  icon: string
  description: string
  ext: string
  language: string
}

const FORMATS: FormatMeta[] = [
  {
    id: 'native_json',
    label: 'Pipesets JSON',
    icon: '📦',
    description: 'Raw flow JSON — re-importable into any Pipesets AI instance',
    ext: 'json',
    language: 'json',
  },
  {
    id: 'openapi',
    label: 'OpenAPI 3.1',
    icon: '📄',
    description: 'YAML spec with one path per tool — plug into any OpenAPI client',
    ext: 'yaml',
    language: 'yaml',
  },
  {
    id: 'langchain',
    label: 'LangChain',
    icon: '🦜',
    description: 'Ready-to-run Python agent using LangChain + ChatOpenAI',
    ext: 'py',
    language: 'python',
  },
  {
    id: 'crewai',
    label: 'CrewAI',
    icon: '🤝',
    description: 'Multi-agent crew with researcher + writer roles',
    ext: 'py',
    language: 'python',
  },
  {
    id: 'autogen',
    label: 'AutoGen',
    icon: '🤖',
    description: 'Microsoft AutoGen ConversableAgent with tool registration',
    ext: 'py',
    language: 'python',
  },
  {
    id: 'docker_compose',
    label: 'Docker Compose',
    icon: '🐳',
    description: 'docker-compose.yml ready to deploy backend + frontend',
    ext: 'yml',
    language: 'yaml',
  },
  {
    id: 'notebook',
    label: 'Notebook',
    icon: '📓',
    description: 'Jupyter Notebook (.ipynb) — step-by-step cells to install, configure and run the agent',
    ext: 'ipynb',
    language: 'json',
  },
  {
    id: 'readme',
    label: 'README',
    icon: '📄',
    description: 'The pipeline\'s Markdown docs (Docs tab) — a setup-and-structure outline if none are written yet',
    ext: 'md',
    language: 'markdown',
  },
  {
    id: 'skill',
    label: 'Agent Skill',
    icon: '🧩',
    description: 'SKILL.md + run script (zip) for Claude Code and other agents — unzip into .claude/skills/; it runs the published pipeline with your PIPESETS_API_KEY',
    ext: 'zip',
    language: 'markdown',
  },
]

// ── Props ─────────────────────────────────────────────────────────────────────

interface ExportModalProps {
  appId: string
  appName: string
  onClose: () => void
}

// ── Component ─────────────────────────────────────────────────────────────────

export function ExportModal({ appId, appName, onClose }: ExportModalProps) {
  const [selected, setSelected] = useState<ExportFormat>('native_json')
  const [preview, setPreview] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchPreview = useCallback(async (fmt: ExportFormat) => {
    setLoading(true)
    setError(null)
    setPreview('')
    try {
      const res = await fetch(`${API_BASE}/api/export/${appId}/preview?format=${fmt}`)
      if (!res.ok) {
        const msg = await res.text()
        let detail = msg
        try { detail = JSON.parse(msg).detail ?? msg } catch { /* not JSON */ }
        throw new Error(detail)
      }
      const text = await res.text()
      setPreview(text)
    } catch (e: any) {
      setError(e.message ?? 'Failed to generate preview')
    } finally {
      setLoading(false)
    }
  }, [appId])

  useEffect(() => {
    fetchPreview(selected)
  }, [selected, fetchPreview])

  const handleDownload = async () => {
    const fmt = FORMATS.find(f => f.id === selected)!
    let blob = new Blob([preview], { type: 'text/plain' })
    let filename = ''
    if (fmt.id === 'skill') {
      // The preview is only the SKILL.md; the server builds the zip
      try {
        const res = await fetch(`${API_BASE}/api/export/${appId}?format=skill`)
        if (!res.ok) throw new Error(await res.text())
        blob = await res.blob()
        filename = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') ?? '')?.[1]
          ?? `${appName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'pipesets-pipeline'}.zip`
      } catch (e: any) {
        setError(e.message ?? 'Failed to download the skill')
        return
      }
    }
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename || (fmt.id === 'native_json'
      ? `${appName.replace(/\s+/g, '_')}_export.json`
      : fmt.id === 'langchain' ? 'langchain_agent.py'
      : fmt.id === 'crewai' ? 'crewai_agent.py'
      : fmt.id === 'autogen' ? 'autogen_agent.py'
      : fmt.id === 'openapi' ? 'openapi.yaml'
      : fmt.id === 'notebook' ? `${appName.replace(/\s+/g, '_')}_notebook.ipynb`
      : fmt.id === 'readme' ? 'README.md'
      : 'docker-compose.yml')
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleCopy = async () => {
    await navigator.clipboard.writeText(preview)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const fmt = FORMATS.find(f => f.id === selected)!

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="export-modal" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="export-modal-header">
          <div>
            <h2 className="export-modal-title">Export App</h2>
            <p className="export-modal-subtitle">{appName}</p>
          </div>
          <button type="button" className="modal-close-btn" onClick={onClose}>✕</button>
        </div>

        <div className="export-modal-body">
          {/* Format picker */}
          <div className="export-format-grid">
            {FORMATS.map(f => (
              <button
                key={f.id}
                type="button"
                className={`export-format-card${selected === f.id ? ' active' : ''}`}
                onClick={() => setSelected(f.id)}
              >
                <span className="export-format-icon">{f.icon}</span>
                <span className="export-format-label">{f.label}</span>
                <span className="export-format-ext">.{f.ext}</span>
              </button>
            ))}
          </div>

          {/* Description */}
          <p className="export-format-desc">{fmt.description}</p>

          {/* Preview pane */}
          <div className="export-preview-pane">
            <div className="export-preview-toolbar">
              <span className="export-preview-lang">{fmt.language}</span>
              <div className="export-preview-actions">
                <button
                  type="button"
                  className="export-action-btn"
                  onClick={handleCopy}
                  disabled={!preview || loading}
                >
                  {copied ? '✓ Copied' : 'Copy'}
                </button>
                <button
                  type="button"
                  className="export-action-btn primary"
                  onClick={handleDownload}
                  disabled={!preview || loading}
                >
                  ↓ Download
                </button>
              </div>
            </div>
            <div className="export-preview-code-wrap">
              {loading && (
                <div className="export-preview-loading">Generating {fmt.label} export…</div>
              )}
              {error && (
                <div className="export-preview-error">{error}</div>
              )}
              {!loading && !error && (
                <pre className="export-preview-code">{preview}</pre>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
