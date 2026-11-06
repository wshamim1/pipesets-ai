import { Handle, Position } from '@xyflow/react'
import type { NodeProps, Node } from '@xyflow/react'
import type { DocLoaderNodeData } from '../types'
import { DB_LOADER_TYPES, getDocLoader, useDocLoaders } from '../utils/docLoaders'
import { NodeIcon } from '../components/NodeIcon'

export function DocLoaderNode({ data, selected }: NodeProps<Node<DocLoaderNodeData, 'doc_loader'>>) {
  useDocLoaders() // re-render when the catalog loads or a custom loader is edited
  const isCardSelected = selected || data.isSelected
  const def = getDocLoader(data.loader_type)
  const isDbBacked = DB_LOADER_TYPES.has(data.loader_type)

  return (
    <div className={`doc-loader-node-card ${isCardSelected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left} id="dl-target-left" className="flow-handle dl-handle" />
      <Handle type="source" position={Position.Left} id="dl-source-left" className="flow-handle dl-handle" />
      <Handle type="target" position={Position.Top} id="dl-target-top" className="flow-handle dl-handle" />
      <Handle type="source" position={Position.Top} id="dl-source-top" className="flow-handle dl-handle" />

      <div className="node-card-header doc-loader-header">
        <div className="node-card-title-row">
          <span className="node-icon"><NodeIcon kind="doc_loader" /></span>
          <span className="node-title">{data.label}</span>
        </div>
        <button type="button" className="node-delete-btn" title="Remove node"
          onClick={(e) => { e.stopPropagation(); data.onDelete?.() }}>✕</button>
      </div>

      <div className="node-card-body">
        <div className="node-badge-row">
          <span className="chip chip-doc-loader">LOADER</span>
          <span className="chip model-chip">{def?.label ?? data.loader_type}</span>
        </div>
        <div className="node-meta-row">
          <span className="meta-item">Chunk: <strong>{data.chunk_strategy}</strong></span>
        </div>
        {!isDbBacked && data.source && (
          <div className="node-meta-row">
            <span className="meta-item doc-source-label" title={data.source}>{data.source.slice(0, 28)}{data.source.length > 28 ? '…' : ''}</span>
          </div>
        )}
      </div>

      <div className="node-card-footer">
        <span className="footer-status dl-footer-status">
          {isCardSelected ? '● Configured in Panel' : isDbBacked ? 'Link a Connection node' : 'Connect to Text Splitter'}
        </span>
      </div>

      <Handle type="target" position={Position.Right} id="dl-target-right" className="flow-handle dl-handle" />
      <Handle type="source" position={Position.Right} id="dl-source-right" className="flow-handle dl-handle" />
      <Handle type="target" position={Position.Bottom} id="dl-target-bottom" className="flow-handle dl-handle" />
      <Handle type="source" position={Position.Bottom} id="dl-source-bottom" className="flow-handle dl-handle" />
    </div>
  )
}
