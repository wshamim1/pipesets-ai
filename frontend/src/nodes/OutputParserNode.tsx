import { Handle, Position } from '@xyflow/react'
import type { NodeProps, Node } from '@xyflow/react'
import type { OutputParserNodeData } from '../types'
import { NodeIcon } from '../components/NodeIcon'


export function OutputParserNode({ data, selected }: NodeProps<Node<OutputParserNodeData, 'output_parser'>>) {
  const isCardSelected = selected || data.isSelected

  return (
    <div className={`output-parser-node-card ${isCardSelected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left}   id="op-target-left"   className="flow-handle op-handle" />
      <Handle type="source" position={Position.Left}   id="op-source-left"   className="flow-handle op-handle" />
      <Handle type="target" position={Position.Top}    id="op-target-top"    className="flow-handle op-handle" />
      <Handle type="source" position={Position.Top}    id="op-source-top"    className="flow-handle op-handle" />

      <div className="node-card-header output-parser-header">
        <div className="node-card-title-row">
          <span className="node-icon"><NodeIcon kind="output_parser" /></span>
          <span className="node-title">{data.label}</span>
        </div>
        <button type="button" className="node-delete-btn" title="Remove node"
          onClick={(e) => { e.stopPropagation(); data.onDelete?.() }}>✕</button>
      </div>

      <div className="node-card-body">
        <div className="node-badge-row">
          <span className="chip chip-cache">OUTPUT PARSER</span>
          <span className="chip model-chip">{data.parser_type}</span>
        </div>
        <div className="node-meta-row">
          <span className="meta-item">Strict: <strong>{data.strict ? 'Yes' : 'No'}</strong></span>
          {data.schema_json && (
            <span className="meta-item" title={data.schema_json}>Schema: <strong>set</strong></span>
          )}
        </div>
      </div>

      <div className="node-card-footer">
        <span className="footer-status op-footer-status">
          {isCardSelected ? '● Active in Bottom Config' : 'LLM → Output Parser'}
        </span>
      </div>

      <Handle type="target" position={Position.Right}  id="op-target-right"  className="flow-handle op-handle" />
      <Handle type="source" position={Position.Right}  id="op-source-right"  className="flow-handle op-handle" />
      <Handle type="target" position={Position.Bottom} id="op-target-bottom" className="flow-handle op-handle" />
      <Handle type="source" position={Position.Bottom} id="op-source-bottom" className="flow-handle op-handle" />
    </div>
  )
}
