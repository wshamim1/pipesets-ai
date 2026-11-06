import { Handle, Position } from '@xyflow/react'
import type { NodeProps, Node } from '@xyflow/react'
import type { TextSplitterNodeData } from '../types'
import { NodeIcon } from '../components/NodeIcon'

const SPLITTER_LABELS: Record<string, string> = {
  recursive_character: 'Recursive Char',
  token: 'Token-based',
  markdown: 'Markdown-aware',
}

export function TextSplitterNode({ data, selected }: NodeProps<Node<TextSplitterNodeData, 'text_splitter'>>) {
  const isCardSelected = selected || data.isSelected

  return (
    <div className={`text-splitter-node-card ${isCardSelected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left} id="ts-target-left" className="flow-handle ts-handle" />
      <Handle type="source" position={Position.Left} id="ts-source-left" className="flow-handle ts-handle" />
      <Handle type="target" position={Position.Top} id="ts-target-top" className="flow-handle ts-handle" />
      <Handle type="source" position={Position.Top} id="ts-source-top" className="flow-handle ts-handle" />

      <div className="node-card-header text-splitter-header">
        <div className="node-card-title-row">
          <span className="node-icon"><NodeIcon kind="text_splitter" /></span>
          <span className="node-title">{data.label}</span>
        </div>
        <button type="button" className="node-delete-btn" title="Remove node"
          onClick={(e) => { e.stopPropagation(); data.onDelete?.() }}>✕</button>
      </div>

      <div className="node-card-body">
        <div className="node-badge-row">
          <span className="chip chip-text-splitter">SPLITTER</span>
          <span className="chip model-chip">{SPLITTER_LABELS[data.splitter_type] ?? data.splitter_type}</span>
        </div>
        <div className="node-meta-row">
          <span className="meta-item">Size: <strong>{data.chunk_size}</strong></span>
          <span className="meta-item">Overlap: <strong>{data.chunk_overlap}</strong></span>
        </div>
      </div>

      <div className="node-card-footer">
        <span className="footer-status ts-footer-status">
          {isCardSelected ? '● Configured in Panel' : 'Connect Loader → Splitter → Embedding'}
        </span>
      </div>

      <Handle type="target" position={Position.Right} id="ts-target-right" className="flow-handle ts-handle" />
      <Handle type="source" position={Position.Right} id="ts-source-right" className="flow-handle ts-handle" />
      <Handle type="target" position={Position.Bottom} id="ts-target-bottom" className="flow-handle ts-handle" />
      <Handle type="source" position={Position.Bottom} id="ts-source-bottom" className="flow-handle ts-handle" />
    </div>
  )
}
