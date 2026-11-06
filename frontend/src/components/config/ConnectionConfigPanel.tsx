import { useState } from 'react'
import type { Node } from '@xyflow/react'
import type { ConnectionNodeData } from '../../types'
import { retestConnection } from '../../utils/connectionHealth'

interface Props {
  activeNode: Node<ConnectionNodeData, 'connection'>
  onUpdate: (id: string, partial: Partial<ConnectionNodeData>) => void
  onDelete: (id: string) => void
  onSave: () => void
  onHealthChecked?: () => void
  readOnly?: boolean
}

export function ConnectionConfigPanel({ activeNode, onUpdate, onDelete, onSave, onHealthChecked, readOnly }: Props) {
  const data = activeNode.data
  const isConnected = data.status === 'connected'
  const [testing, setTesting] = useState(false)

  const handleRetest = async () => {
    setTesting(true)
    onUpdate(activeNode.id, await retestConnection(data.connection_id))
    onHealthChecked?.()
    setTesting(false)
  }

  return (
    <div className="bottom-config-grid">
      {/* 1. Identity & Type */}
      <div className="config-card">
        <h4 className="card-heading">1. Connection Details</h4>
        <div className="form-group">
          <label className="field-label">Label</label>
          <input
            type="text"
            className="field-input"
            value={data.label}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { label: e.target.value })}
          />
        </div>
        <div className="form-group">
          <label className="field-label">Type</label>
          <input
            type="text"
            className="field-input"
            value={data.connection_type.toUpperCase()}
            disabled
            style={{ background: '#f8fafc', color: '#64748b' }}
          />
        </div>
        <div className="form-group">
          <label className="field-label">Description</label>
          <input
            type="text"
            className="field-input"
            value={data.description}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { description: e.target.value })}
          />
        </div>
      </div>

      {/* 2. Connection Status */}
      <div className="config-card">
        <h4 className="card-heading">2. Health Status</h4>
        <div
          style={{
            padding: '10px 12px',
            borderRadius: 8,
            border: `1px solid ${isConnected ? '#bbf7d0' : '#fecaca'}`,
            background: isConnected ? '#f0fdf4' : '#fef2f2',
            color: isConnected ? '#166534' : '#991b1b',
            fontSize: 12,
            fontWeight: 600,
          }}
        >
          {isConnected ? '🟢 Connection Verified' : '🔴 Connection Error'}
        </div>
        {data.status_msg && (
          <p className="field-hint" style={{ marginTop: 6, color: '#475569', fontSize: 11 }}>
            {data.status_msg}
          </p>
        )}
        {data.connection_id && (
          <button
            type="button"
            className="save-btn"
            style={{ marginTop: 8 }}
            onClick={handleRetest}
            disabled={testing}
          >
            {testing ? 'Testing…' : 'Retest connection'}
          </button>
        )}
      </div>

      {/* 3. Credentials Preview */}
      <div className="config-card">
        <h4 className="card-heading">3. Parameters</h4>
        <div style={{ maxHeight: 110, overflowY: 'auto' }}>
          {Object.entries(data.config || {}).map(([k, v]) => (
            <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, padding: '3px 0' }}>
              <span style={{ color: '#64748b', fontWeight: 600 }}>{k}:</span>
              <span className="font-mono" style={{ color: '#0f172a' }}>
                {k.toLowerCase().includes('password') || k.toLowerCase().includes('secret') || k.toLowerCase().includes('key')
                  ? '••••••••'
                  : String(v)}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* 4. Actions */}
      <div className="config-card">
        <h4 className="card-heading">4. Node Actions</h4>
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
