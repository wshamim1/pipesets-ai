import { useState, useEffect } from 'react'
import { API_BASE } from '../types'

const ENV_KEYS = [
  { key: 'OPENAI_API_KEY',       label: 'OpenAI API Key',       provider: 'OpenAI' },
  { key: 'ANTHROPIC_API_KEY',    label: 'Anthropic API Key',    provider: 'Anthropic' },
  { key: 'GROQ_API_KEY',         label: 'Groq API Key',         provider: 'Groq' },
  { key: 'GEMINI_API_KEY',       label: 'Gemini API Key',       provider: 'Google' },
  { key: 'COHERE_API_KEY',       label: 'Cohere API Key',       provider: 'Cohere' },
  { key: 'MISTRAL_API_KEY',      label: 'Mistral API Key',      provider: 'Mistral' },
  { key: 'TOGETHERAI_API_KEY',   label: 'TogetherAI API Key',   provider: 'Together' },
  { key: 'FIREWORKS_AI_API_KEY', label: 'Fireworks AI API Key', provider: 'Fireworks' },
  { key: 'AZURE_API_KEY',        label: 'Azure OpenAI Key',     provider: 'Azure' },
  { key: 'TAVILY_API_KEY',       label: 'Tavily Search Key',    provider: 'Tools' },
]

export function AdminPanel() {
  const [values, setValues]   = useState<Record<string, string>>({})
  const [saved, setSaved]     = useState<Record<string, boolean>>({})
  const [visible, setVisible] = useState<Record<string, boolean>>({})
  const [backendUrl, setBackendUrl] = useState(API_BASE)
  const [health, setHealth]   = useState<'unknown' | 'ok' | 'error'>('unknown')

  // Pre-fill from localStorage on mount
  useEffect(() => {
    const stored: Record<string, string> = {}
    ENV_KEYS.forEach(({ key }) => {
      const v = localStorage.getItem(`env_${key}`)
      if (v) stored[key] = v
    })
    setValues(stored)
  }, [])

  // Check backend health
  const checkHealth = () => {
    fetch(`${backendUrl}/api/health`)
      .then(r => r.ok ? setHealth('ok') : setHealth('error'))
      .catch(() => setHealth('error'))
  }

  const handleSave = (key: string) => {
    const val = values[key] ?? ''
    if (val) localStorage.setItem(`env_${key}`, val)
    else localStorage.removeItem(`env_${key}`)
    setSaved(prev => ({ ...prev, [key]: true }))
    setTimeout(() => setSaved(prev => ({ ...prev, [key]: false })), 1500)
  }

  const toggleVisible = (key: string) =>
    setVisible(prev => ({ ...prev, [key]: !prev[key] }))

  return (
    <div className="admin-panel-body">
      {/* Backend connection */}
      <div className="admin-section">
        <div className="admin-section-title">Backend</div>
        <div className="admin-row">
          <input
            className="admin-input"
            value={backendUrl}
            onChange={e => setBackendUrl(e.target.value)}
            placeholder="http://localhost:8000"
          />
          <button type="button" className="admin-check-btn" onClick={checkHealth}>
            Check
          </button>
          {health === 'ok'    && <span className="admin-badge ok">✓ Connected</span>}
          {health === 'error' && <span className="admin-badge error">✗ Unreachable</span>}
        </div>
      </div>

      {/* API keys */}
      <div className="admin-section">
        <div className="admin-section-title">API Keys (stored in browser only)</div>
        <div className="admin-keys-list">
          {ENV_KEYS.map(({ key, label, provider }) => (
            <div key={key} className="admin-key-row">
              <div className="admin-key-meta">
                <span className="admin-key-label">{label}</span>
                <span className="admin-key-provider">{provider}</span>
              </div>
              <div className="admin-key-input-row">
                <input
                  type={visible[key] ? 'text' : 'password'}
                  className="admin-input admin-input--key"
                  value={values[key] ?? ''}
                  placeholder="sk-…"
                  onChange={e => setValues(prev => ({ ...prev, [key]: e.target.value }))}
                />
                <button type="button" className="admin-eye-btn" onClick={() => toggleVisible(key)}>
                  {visible[key] ? '🙈' : '👁'}
                </button>
                <button
                  type="button"
                  className={`admin-save-btn${saved[key] ? ' saved' : ''}`}
                  onClick={() => handleSave(key)}
                >
                  {saved[key] ? '✓' : 'Save'}
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <p className="admin-note">
        Keys are saved in <code>localStorage</code> only — they never leave your browser and are not sent to the backend.
        Set them as environment variables server-side for production use.
      </p>
    </div>
  )
}
