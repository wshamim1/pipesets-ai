import type { LlmNodeData, ProviderOption, FlowNode } from '../../types'
import { ApiKeyField } from './ApiKeyField'

interface Props {
  activeNode: FlowNode
  providers: ProviderOption[]
  onUpdate: (nodeId: string, fields: Record<string, any>) => void
  onDelete: (nodeId: string) => void
  onSave: () => void
  readOnly?: boolean
}

export function LlmConfigPanel({ activeNode, providers, onUpdate, onDelete, onSave, readOnly }: Props) {
  const data = activeNode.data as LlmNodeData
  const activeProviderObj = providers.find((p) => p.id === data.provider)
  const modelList = activeProviderObj ? activeProviderObj.models : ['gpt-4o']
  const timeoutMs = data.timeout_ms ?? 45000
  const maxRetries = data.max_retries ?? 1
  const retryBackoffMs = data.retry_backoff_ms ?? 500
  const fallbackProvider = data.fallback_provider ?? ''
  const fallbackProviderObj = providers.find((p) => p.id === fallbackProvider)
  const fallbackModelList = fallbackProviderObj ? fallbackProviderObj.models : []

  return (
    <div className="bottom-config-grid">
      <div className="config-card">
        <h4 className="card-heading">1. Model &amp; Provider</h4>
        <div className="form-group">
          <label className="field-label">Node Label</label>
          <input type="text" className="field-input" value={data.label} disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { label: e.target.value })} />
        </div>
        <div className="form-row">
          <div className="form-group flex-1">
            <label className="field-label">Provider</label>
            <select className="field-select" value={data.provider} disabled={readOnly}
              onChange={(e) => {
                const found = providers.find((p) => p.id === e.target.value)
                onUpdate(activeNode.id, { provider: e.target.value, model: found ? found.models[0] : data.model })
              }}>
              {providers.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
          <div className="form-group flex-1">
            <label className="field-label">Model</label>
            <select className="field-select" value={data.model} disabled={readOnly}
              onChange={(e) => onUpdate(activeNode.id, { model: e.target.value })}>
              {modelList.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
        </div>
      </div>

      <div className="config-card">
        <h4 className="card-heading">2. Sampling &amp; Temperature</h4>
        <div className="slider-box">
          <div className="slider-header">
            <label className="field-label">Temperature</label>
            <span className="slider-tag">{data.temperature}</span>
          </div>
          <input type="range" min="0" max="2" step="0.05" className="field-slider" value={data.temperature}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { temperature: parseFloat(e.target.value) })} />
        </div>
        <div className="form-row">
          <div className="form-group flex-1">
            <label className="field-label">Max Tokens</label>
            <input type="number" className="field-input" min="64" max="8192" step="64" value={data.max_tokens}
              disabled={readOnly}
              onChange={(e) => onUpdate(activeNode.id, { max_tokens: parseInt(e.target.value) || 1024 })} />
          </div>
          <div className="form-group flex-1">
            <label className="field-label">Top P</label>
            <input type="number" className="field-input" min="0" max="1" step="0.05" value={data.top_p}
              disabled={readOnly}
              onChange={(e) => onUpdate(activeNode.id, { top_p: parseFloat(e.target.value) || 1.0 })} />
          </div>
        </div>
      </div>

      <div className="config-card">
        <h4 className="card-heading">3. Credentials &amp; URL</h4>
        <div className="form-group">
          <label className="field-label">API Key</label>
          <ApiKeyField provider={data.provider} value={data.api_key} readOnly={readOnly}
            emptyLabel={data.provider === 'mock' ? 'Not needed' : '— No key —'} placeholder="sk-..."
            onChange={(v) => onUpdate(activeNode.id, { api_key: v })} />
        </div>
        <div className="form-group">
          <label className="field-label">Base URL (Ollama/llama.cpp/vLLM)</label>
          <input type="text" className="field-input" placeholder={data.provider === 'llamacpp' ? 'http://localhost:8080' : 'http://localhost:11434'} value={data.base_url}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { base_url: e.target.value })} />
        </div>
      </div>

      <div className="config-card">
        <h4 className="card-heading">4. Instructions &amp; Save</h4>
        <div className="form-group">
          <label className="field-label">System Prompt</label>
          <textarea rows={3} className="field-textarea" placeholder="System instructions..." value={data.system_prompt}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { system_prompt: e.target.value })} />
        </div>

        <div className="form-row">
          <div className="form-group flex-1">
            <label className="field-label" htmlFor={`skill-mode-${activeNode.id}`}>Skills</label>
            <select id={`skill-mode-${activeNode.id}`} className="field-select" value={data.skill_mode ?? 'on_demand'} disabled={readOnly}
              onChange={(e) => onUpdate(activeNode.id, { skill_mode: e.target.value })}>
              <option value="on_demand">Load when needed</option>
              <option value="always">Always in the prompt</option>
            </select>
          </div>
          {(data.skill_mode ?? 'on_demand') === 'on_demand' && (
            <div className="form-group" style={{ width: 90 }}>
              <label className="field-label" htmlFor={`skill-max-${activeNode.id}`}>Max loaded</label>
              <input id={`skill-max-${activeNode.id}`} type="number" className="field-input" min="1" max="10"
                value={data.max_active_skills ?? 3} disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { max_active_skills: Math.max(1, Math.min(10, parseInt(e.target.value) || 3)) })} />
            </div>
          )}
        </div>
        <span className="field-hint">
          {(data.skill_mode ?? 'on_demand') === 'on_demand'
            ? 'The model sees each attached skill’s “when to use” and loads the ones a request needs; a skill’s tools stay hidden until then.'
            : 'Every attached skill’s instructions go in the prompt and all tools are on — for small models that don’t call tools well.'}
        </span>

        <div className="form-group">
          <label className="field-label">Timeout (ms)</label>
          <input
            type="number"
            className="field-input"
            min="1000"
            max="300000"
            step="500"
            value={timeoutMs}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { timeout_ms: parseInt(e.target.value) || 45000 })}
          />
        </div>

        <div className="form-row">
          <div className="form-group flex-1">
            <label className="field-label">Max Retries</label>
            <input
              type="number"
              className="field-input"
              min="0"
              max="5"
              step="1"
              value={maxRetries}
              disabled={readOnly}
              onChange={(e) => onUpdate(activeNode.id, { max_retries: parseInt(e.target.value) || 0 })}
            />
          </div>
          <div className="form-group flex-1">
            <label className="field-label">Retry Backoff (ms)</label>
            <input
              type="number"
              className="field-input"
              min="0"
              max="10000"
              step="100"
              value={retryBackoffMs}
              disabled={readOnly}
              onChange={(e) => onUpdate(activeNode.id, { retry_backoff_ms: parseInt(e.target.value) || 0 })}
            />
          </div>
        </div>

        <div className="form-row">
          <div className="form-group flex-1">
            <label className="field-label">Fallback Provider</label>
            <select
              className="field-select"
              value={fallbackProvider}
              disabled={readOnly}
              onChange={(e) => {
                const selectedProvider = e.target.value
                const selectedProviderObj = providers.find((p) => p.id === selectedProvider)
                onUpdate(activeNode.id, {
                  fallback_provider: selectedProvider,
                  fallback_model: selectedProvider ? (selectedProviderObj?.models?.[0] ?? '') : '',
                })
              }}
            >
              <option value="">None</option>
              {providers.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
          <div className="form-group flex-1">
            <label className="field-label">Fallback Model</label>
            <select
              className="field-select"
              value={data.fallback_model ?? ''}
              disabled={readOnly || !fallbackProvider}
              onChange={(e) => onUpdate(activeNode.id, { fallback_model: e.target.value })}
            >
              {!fallbackProvider && <option value="">Select fallback provider</option>}
              {fallbackProvider && fallbackModelList.length === 0 && <option value="">No models found</option>}
              {fallbackModelList.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
        </div>

        {fallbackProvider && (
          <>
            <div className="form-group">
              <label className="field-label">Fallback API Key</label>
              <ApiKeyField provider={fallbackProvider} value={data.fallback_api_key} readOnly={readOnly}
                emptyLabel="— Fallback provider's default key —"
                onChange={(v) => onUpdate(activeNode.id, { fallback_api_key: v })} />
            </div>
            <div className="form-group">
              <label className="field-label">Fallback Base URL</label>
              <input
                type="text"
                className="field-input"
                placeholder="Optional fallback base URL"
                value={data.fallback_base_url ?? ''}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { fallback_base_url: e.target.value })}
              />
            </div>
          </>
        )}

        {!readOnly && (
          <div className="card-actions-row">
            <button type="button" className="save-btn" onClick={onSave}>Save to App</button>
            <button type="button" className="delete-btn" onClick={() => onDelete(activeNode.id)}>Delete Node</button>
          </div>
        )}
      </div>
    </div>
  )
}
