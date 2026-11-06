import { Handle, Position } from '@xyflow/react'
import type { NodeProps, Node } from '@xyflow/react'
import type { CacheNodeData } from '../types'
import { NodeIcon } from '../components/NodeIcon'

export function CacheNode({ data, selected }: NodeProps<Node<CacheNodeData, 'cache'>>) {
  const isCardSelected = selected || data.isSelected
  const scopeLabel: Record<string, string> = { prompt: 'Prompt Scope', model: 'Model Scope', strict: 'Strict Scope' }
  const ttlLabel = data.ttl_seconds >= 3600
    ? `${Math.round(data.ttl_seconds / 3600)}h TTL`
    : `${Math.round(data.ttl_seconds / 60)}m TTL`

  return (
    <div className={`cache-node-card ${isCardSelected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left} id="cache-target-left" className="flow-handle cache-handle" />
      <Handle type="source" position={Position.Left} id="cache-source-left" className="flow-handle cache-handle" />
      <Handle type="target" position={Position.Top} id="cache-target-top" className="flow-handle cache-handle" />
      <Handle type="source" position={Position.Top} id="cache-source-top" className="flow-handle cache-handle" />

      <div className="node-card-header cache-header">
        <div className="node-card-title-row">
          <span className="node-icon"><NodeIcon kind="cache" /></span>
          <span className="node-title">{data.label}</span>
        </div>
        <button type="button" className="node-delete-btn" title="Remove node"
          onClick={(e) => { e.stopPropagation(); data.onDelete?.() }}>✕</button>
      </div>

      <div className="node-card-body">
        <div className="node-badge-row">
          <span className="chip chip-cache">CACHE</span>
          <span className="chip model-chip">{scopeLabel[data.scope] ?? data.scope}</span>
        </div>
        <div className="node-meta-row">
          <span className="meta-item"><strong>{ttlLabel}</strong></span>
          <span className="meta-item">Max: <strong>{data.max_size.toLocaleString()}</strong></span>
        </div>
      </div>

      <div className="node-card-footer">
        <span className="footer-status cache-footer-status">
          {isCardSelected ? '● Configured in Panel' : 'Connect to LLM to cache'}
        </span>
      </div>

      <Handle type="target" position={Position.Right} id="cache-target-right" className="flow-handle cache-handle" />
      <Handle type="source" position={Position.Right} id="cache-source-right" className="flow-handle cache-handle" />
      <Handle type="target" position={Position.Bottom} id="cache-target-bottom" className="flow-handle cache-handle" />
      <Handle type="source" position={Position.Bottom} id="cache-source-bottom" className="flow-handle cache-handle" />
    </div>
  )
}
