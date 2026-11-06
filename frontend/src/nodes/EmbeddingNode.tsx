import { Handle, Position } from '@xyflow/react'
import type { NodeProps, Node } from '@xyflow/react'
import type { EmbeddingNodeData } from '../types'
import { NodeIcon } from '../components/NodeIcon'

const PROVIDER_LABELS: Record<string, string> = {
  openai:       'OpenAI',
  local:        'Local',
  anthropic:    'Anthropic',
  cohere:       'Cohere',
  google:       'Google',
  azure_openai: 'Azure OpenAI',
  mistral:      'Mistral',
  ollama:       'Ollama',
  llamacpp:     'llama.cpp',
  bedrock:      'Bedrock',
  voyage:       'Voyage AI',
  nomic:        'Nomic',
}

export function EmbeddingNode({ data, selected }: NodeProps<Node<EmbeddingNodeData, 'embedding'>>) {
  const isCardSelected = selected || data.isSelected

  return (
    <div className={`embedding-node-card ${isCardSelected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left} id="emb-target-left" className="flow-handle emb-handle" />
      <Handle type="source" position={Position.Left} id="emb-source-left" className="flow-handle emb-handle" />
      <Handle type="target" position={Position.Top} id="emb-target-top" className="flow-handle emb-handle" />
      <Handle type="source" position={Position.Top} id="emb-source-top" className="flow-handle emb-handle" />

      <div className="node-card-header embedding-header">
        <div className="node-card-title-row">
          <span className="node-icon"><NodeIcon kind="embedding" /></span>
          <span className="node-title">{data.label}</span>
        </div>
        <button type="button" className="node-delete-btn" title="Remove node"
          onClick={(e) => { e.stopPropagation(); data.onDelete?.() }}>✕</button>
      </div>

      <div className="node-card-body">
        <div className="node-badge-row">
          <span className="chip chip-embedding">EMBED</span>
          <span className="chip model-chip">{PROVIDER_LABELS[data.provider] ?? data.provider}</span>
        </div>
        <div className="node-meta-row">
          <span className="meta-item">{data.model}</span>
        </div>
      </div>

      <div className="node-card-footer">
        <span className="footer-status emb-footer-status">
          {isCardSelected ? '● Configured in Panel' : 'Connect to Vector Store'}
        </span>
      </div>

      <Handle type="target" position={Position.Right} id="emb-target-right" className="flow-handle emb-handle" />
      <Handle type="source" position={Position.Right} id="emb-source-right" className="flow-handle emb-handle" />
      <Handle type="target" position={Position.Bottom} id="emb-target-bottom" className="flow-handle emb-handle" />
      <Handle type="source" position={Position.Bottom} id="emb-source-bottom" className="flow-handle emb-handle" />
    </div>
  )
}
