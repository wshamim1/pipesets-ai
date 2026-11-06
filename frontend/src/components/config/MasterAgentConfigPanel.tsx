import type { MasterAgentNodeData, FlowNode } from '../../types'
import { ApiKeyField } from './ApiKeyField'
import { HelpLink } from '../docs/HelpLink'

interface Props {
  activeNode: FlowNode
  onUpdate: (nodeId: string, fields: Record<string, any>) => void
  onDelete: (nodeId: string) => void
  onSave: () => void
  readOnly?: boolean
}

const PROVIDERS = [
  { id: 'openai', label: 'OpenAI', models: ['gpt-5.5', 'gpt-5.4-mini', 'gpt-4.1', 'gpt-4o'] },
  { id: 'anthropic', label: 'Anthropic', models: ['claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5'] },
  { id: 'groq', label: 'Groq', models: ['openai/gpt-oss-120b', 'openai/gpt-oss-20b'] },
  { id: 'gemini', label: 'Google Gemini', models: ['gemini-3.5-flash', 'gemini-2.5-pro'] },
  { id: 'ollama', label: 'Ollama (Local)', models: ['llama3.2', 'llama3.1', 'mistral'] },
  { id: 'llamacpp', label: 'llama.cpp (Local)', models: ['default'] },
  { id: 'mock', label: 'Mock / Simulator', models: ['mock-gpt-4', 'mock-claude'] },
]

export function MasterAgentConfigPanel({ activeNode, onUpdate, onDelete, onSave, readOnly }: Props) {
  const data = activeNode.data as MasterAgentNodeData
  const providerModels = PROVIDERS.find((p) => p.id === data.provider)?.models ?? []

  return (
    <div className="bottom-config-grid">
      {/* Card 1 — Identity & Goal */}
      <div className="config-card">
        <h4 className="card-heading">1. Identity &amp; Goal</h4>
        <div className="form-group">
          <label className="field-label">Node Label</label>
          <input
            type="text"
            className="field-input"
            value={data.label}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { label: e.target.value })}
          />
        </div>
        <div className="form-group">
          <label className="field-label">Agent Goal</label>
          <textarea
            rows={3}
            className="field-textarea"
            placeholder="e.g. Research the topic, delegate writing to a writer agent, then have a reviewer agent check the output."
            value={data.goal}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { goal: e.target.value })}
          />
          <span className="field-hint">The master agent uses this as its top-level instruction for planning and delegation.</span>
        </div>
      </div>

      {/* Card 2 — LLM */}
      <div className="config-card">
        <h4 className="card-heading">2. LLM (Planning)</h4>
        <div className="form-group">
          <label className="field-label">Provider</label>
          <select
            className="field-select"
            value={data.provider}
            disabled={readOnly}
            onChange={(e) => {
              const prov = PROVIDERS.find((p) => p.id === e.target.value)
              onUpdate(activeNode.id, { provider: e.target.value, model: prov?.models[0] ?? '' })
            }}
          >
            {PROVIDERS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
        </div>
        <div className="form-group">
          <label className="field-label">Model</label>
          <select
            className="field-select"
            value={data.model}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { model: e.target.value })}
          >
            {providerModels.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
        <div className="form-group">
          <label className="field-label">API Key</label>
          <ApiKeyField provider={data.provider} value={data.api_key} readOnly={readOnly}
            emptyLabel="— No key (Ollama / llama.cpp / Mock) —" placeholder="sk-…"
            onChange={(v) => onUpdate(activeNode.id, { api_key: v })} />
        </div>
      </div>

      {/* Card 3 — Coordination */}
      <div className="config-card">
        <h4 className="card-heading">3. Coordination Strategy<HelpLink page="05-agents-workflows-skills" section="master-and-child-agents" label="Master and Child agents" /></h4>
        <div className="form-group">
          <label className="field-label">Strategy</label>
          <select
            className="field-select"
            value={data.strategy}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { strategy: e.target.value as MasterAgentNodeData['strategy'] })}
          >
            <option value="sequential">Sequential — Run child agents one at a time, pass outputs forward</option>
            <option value="parallel">Parallel — Run all child agents simultaneously, merge results</option>
            <option value="dynamic">Dynamic — Master decides at runtime which child to call next</option>
          </select>
          <span className="field-hint">
            {data.strategy === 'sequential' && 'Each child receives the output of the previous child as context.'}
            {data.strategy === 'parallel' && 'All children run at the same time. Master merges and summarises results.'}
            {data.strategy === 'dynamic' && 'Master uses LLM reasoning to choose the next child at each step.'}
          </span>
        </div>
        <div className="form-group">
          <label className="field-label">Max Steps</label>
          <input
            type="number"
            className="field-input"
            min={1}
            max={20}
            step={1}
            value={data.max_steps}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { max_steps: parseInt(e.target.value) || 5 })}
          />
          <span className="field-hint">Hard limit on total agent steps. Prevents infinite loops.</span>
        </div>
      </div>

      {/* Card 4 — Actions */}
      <div className="config-card">
        <h4 className="card-heading">4. Node Actions</h4>
        <div className="tool-status-box ma-status-box">
          <span className="status-dot ma-dot" />
          <span>Master agent orchestrates connected Child Agent nodes</span>
        </div>
        <div className="agent-wiring-hint">
          <p className="field-hint">
            <strong>How to wire:</strong> Drag Child Agent nodes onto the canvas and connect them to this Master Agent node using edges.
            The master will delegate tasks to children based on their roles.
          </p>
        </div>
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
