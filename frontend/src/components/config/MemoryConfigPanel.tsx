import { API_BASE } from '../../types'
import type { MemoryNodeData, FlowNode } from '../../types'

interface Props {
  activeNode: FlowNode
  onUpdate: (nodeId: string, fields: Record<string, any>) => void
  onDelete: (nodeId: string) => void
  onSave: () => void
  readOnly?: boolean
}

export function MemoryConfigPanel({ activeNode, onUpdate, onDelete, onSave, readOnly }: Props) {
  const data = activeNode.data as MemoryNodeData

  return (
    <div className="bottom-config-grid">
      <div className="config-card">
        <h4 className="card-heading">1. Identity &amp; Session</h4>
        <div className="form-group">
          <label className="field-label">Node Label</label>
          <input type="text" className="field-input" value={data.label} disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { label: e.target.value })} />
        </div>
        <div className="form-group">
          <label className="field-label">Session ID</label>
          <input type="text" className="field-input code-font" value={data.session_id} disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { session_id: e.target.value })} />
          <span className="field-hint">Unique per conversation. Messages are stored under this key.</span>
        </div>
      </div>

      <div className="config-card">
        <h4 className="card-heading">2. Memory Strategy</h4>
        <div className="form-group">
          <label className="field-label">Strategy</label>
          <select className="field-select" value={data.strategy} disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { strategy: e.target.value as MemoryNodeData['strategy'] })}>
            <option value="sliding_window">Sliding Window — Drop oldest turns over budget</option>
            <option value="summarize">Summarize — Keep system + last 4 turns</option>
            <option value="last_k">Last K — Keep last 8 messages</option>
          </select>
        </div>
        <div className="form-group">
          <label className="field-label">Token Budget</label>
          <input type="number" className="field-input" min="512" max="32768" step="256" value={data.token_budget}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { token_budget: parseInt(e.target.value) || 4096 })} />
          <span className="field-hint">Max tokens of history injected into each LLM call.</span>
        </div>
      </div>

      <div className="config-card">
        <h4 className="card-heading">3. Session TTL</h4>
        <div className="form-group">
          <label className="field-label">Session TTL (hours)</label>
          <input type="number" className="field-input" min="1" max="720" step="1" value={data.session_ttl_hours}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { session_ttl_hours: parseInt(e.target.value) || 24 })} />
          <span className="field-hint">Session messages older than this will be ignored.</span>
        </div>
      </div>

      <div className="config-card">
        <h4 className="card-heading">4. Long-term Memory</h4>
        <div className="form-group">
          <label className="field-label">
            <input type="checkbox" checked={!!data.long_term} disabled={readOnly}
              onChange={(e) => onUpdate(activeNode.id, { long_term: e.target.checked })} />
            {' '}Remember facts about the user across sessions
          </label>
          <span className="field-hint">
            Recalls what this user said in earlier sessions (preferences, profile, goals) and learns new facts after
            each answer, with PII removed. Needs the workspace's opt-in (Monitor → Sessions → Long-term). The user is
            whoever is signed in here, and the <code>user</code> field on API and MCP runs.
          </span>
        </div>
        {data.long_term && (
          <>
            <div className="form-group">
              <label className="field-label">Facts recalled per run</label>
              <input type="number" className="field-input" min="1" max="50" step="1" value={data.recall_k ?? 8}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { recall_k: Math.max(1, parseInt(e.target.value) || 8) })} />
              <span className="field-hint">All of them up to this many; past it, the ones most related to the prompt.</span>
            </div>
            <div className="form-group">
              <label className="field-label">
                <input type="checkbox" checked={data.extract_facts ?? true} disabled={readOnly}
                  onChange={(e) => onUpdate(activeNode.id, { extract_facts: e.target.checked })} />
                {' '}Learn new facts from each conversation
              </label>
              <span className="field-hint">Off: only recall what is already remembered (or added by hand).</span>
            </div>
          </>
        )}
      </div>

      <div className="config-card">
        <h4 className="card-heading">5. Node Actions</h4>
        <div className="tool-status-box memory-status-box">
          <span className="status-dot mem-dot" />
          <span>Session persisted in SQLite</span>
        </div>
        {!readOnly && (
          <div className="card-actions-row">
            <button type="button" className="mem-clear-btn"
              onClick={async () => {
                await fetch(`${API_BASE}/api/memory/${encodeURIComponent(data.session_id)}`, { method: 'DELETE' })
              }}>
              🗑 Clear Session
            </button>
            <button type="button" className="save-btn" onClick={onSave}>Save to App</button>
            <button type="button" className="delete-btn" onClick={() => onDelete(activeNode.id)}>Delete Node</button>
          </div>
        )}
      </div>
    </div>
  )
}
