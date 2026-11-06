import { API_BASE } from '../../types'
import type { CacheNodeData, FlowNode } from '../../types'
import { CacheStatsPanel } from '../CacheStatsPanel'

interface Props {
  activeNode: FlowNode
  onUpdate: (nodeId: string, fields: Record<string, any>) => void
  onDelete: (nodeId: string) => void
  onSave: () => void
  readOnly?: boolean
}

export function CacheConfigPanel({ activeNode, onUpdate, onDelete, onSave, readOnly }: Props) {
  const data = activeNode.data as CacheNodeData

  return (
    <div className="bottom-config-grid">
      <div className="config-card">
        <h4 className="card-heading">1. Identity &amp; Scope</h4>
        <div className="form-group">
          <label className="field-label">Node Label</label>
          <input type="text" className="field-input" value={data.label} disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { label: e.target.value })} />
        </div>
        <div className="form-group">
          <label className="field-label">Cache Scope</label>
          <select className="field-select" value={data.scope} disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { scope: e.target.value as CacheNodeData['scope'] })}>
            <option value="prompt">Prompt — Cache by prompt text only</option>
            <option value="model">Model — Cache by prompt + model name</option>
            <option value="strict">Strict — Cache by prompt + model + all params</option>
          </select>
          <span className="field-hint">Wider scope = more hits. Strict scope = precise matching.</span>
        </div>
      </div>

      <div className="config-card">
        <h4 className="card-heading">2. TTL &amp; Capacity</h4>
        <div className="form-group">
          <label className="field-label">TTL (seconds)</label>
          <input type="number" className="field-input" min="60" max="604800" step="60" value={data.ttl_seconds}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { ttl_seconds: parseInt(e.target.value) || 3600 })} />
          <span className="field-hint">
            {`${Math.round(data.ttl_seconds / 3600 * 10) / 10}h — Cache entries expire after this duration.`}
          </span>
        </div>
        <div className="form-group">
          <label className="field-label">Max Entries</label>
          <input type="number" className="field-input" min="10" max="10000" step="50" value={data.max_size}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { max_size: parseInt(e.target.value) || 500 })} />
          <span className="field-hint">Soft cap for display. SQLite enforces no hard limit by default.</span>
        </div>
      </div>

      <div className="config-card">
        <h4 className="card-heading">3. Cache Stats</h4>
        <CacheStatsPanel />
      </div>

      <div className="config-card">
        <h4 className="card-heading">4. Node Actions</h4>
        <div className="tool-status-box cache-status-box">
          <span className="status-dot cache-dot" />
          <span>Responses cached in SQLite</span>
        </div>
        {!readOnly && (
          <div className="card-actions-row">
            <button type="button" className="cache-clear-btn"
              onClick={async () => { await fetch(`${API_BASE}/api/cache`, { method: 'DELETE' }) }}>
              🗑 Clear All Cache
            </button>
            <button type="button" className="save-btn" onClick={onSave}>Save to App</button>
            <button type="button" className="delete-btn" onClick={() => onDelete(activeNode.id)}>Delete Node</button>
          </div>
        )}
      </div>
    </div>
  )
}
