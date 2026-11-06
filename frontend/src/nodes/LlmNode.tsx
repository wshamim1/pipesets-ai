import { Handle, Position } from '@xyflow/react'
import type { NodeProps, Node } from '@xyflow/react'
import type { LlmNodeData } from '../types'
import { DebugBadges } from './DebugBadges'
import { NodeIcon } from '../components/NodeIcon'

export function LlmNode({ data, selected }: NodeProps<Node<LlmNodeData, 'llm'>>) {
  const isCardSelected = selected || data.isSelected

  const getProviderBadgeClass = (provider: string) => {
    switch (provider) {
      case 'openai': return 'chip chip-openai'
      case 'anthropic': return 'chip chip-anthropic'
      case 'ollama': return 'chip chip-ollama'
      case 'llamacpp': return 'chip chip-llamacpp'
      case 'jan': return 'chip chip-jan'
      case 'typesafe': return 'chip chip-typesafe'
      default: return 'chip chip-mock'
    }
  }

  return (
    <div className={`llm-node-card ${isCardSelected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left} id="llm-target-left" className="flow-handle" />
      <Handle type="source" position={Position.Left} id="llm-source-left" className="flow-handle" />
      <Handle type="target" position={Position.Top} id="llm-target-top" className="flow-handle" />
      <Handle type="source" position={Position.Top} id="llm-source-top" className="flow-handle" />

      <div className="node-card-header">
        <div className="node-card-title-row">
          <span className="node-icon"><NodeIcon kind="llm" /></span>
          <span className="node-title">{data.label}</span>
        </div>
        <DebugBadges data={data} />
        <button type="button" className="node-delete-btn" title="Remove node"
          onClick={(e) => { e.stopPropagation(); data.onDelete?.() }}>✕</button>
      </div>

      <div className="node-card-body">
        <div className="node-badge-row">
          <span className={getProviderBadgeClass(data.provider)}>{data.provider.toUpperCase()}</span>
          <span className="chip model-chip">{data.model}</span>
        </div>
        <div className="node-meta-row">
          <span className="meta-item">Temp: <strong>{data.temperature}</strong></span>
          <span className="meta-item">Max: <strong>{data.max_tokens}</strong></span>
        </div>
      </div>

      <div className="node-card-footer">
        <span className="footer-status">
          {isCardSelected ? '● Active in Bottom Config' : 'Click to edit below'}
        </span>
      </div>

      <Handle type="target" position={Position.Right} id="llm-target-right" className="flow-handle" />
      <Handle type="source" position={Position.Right} id="llm-source-right" className="flow-handle" />
      <Handle type="target" position={Position.Bottom} id="llm-target-bottom" className="flow-handle" />
      <Handle type="source" position={Position.Bottom} id="llm-source-bottom" className="flow-handle" />
    </div>
  )
}
