import { Handle, Position } from '@xyflow/react'
import type { NodeProps, Node } from '@xyflow/react'
import type { MasterAgentNodeData } from '../types'
import { NodeIcon } from '../components/NodeIcon'

const STRATEGY_LABELS: Record<string, string> = {
  sequential: 'Sequential',
  parallel: 'Parallel',
  dynamic: 'Dynamic',
}

export function MasterAgentNode({ data, selected }: NodeProps<Node<MasterAgentNodeData, 'master_agent'>>) {
  const isCardSelected = selected || data.isSelected

  return (
    <div className={`master-agent-node-card ${isCardSelected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left} id="ma-target-left" className="flow-handle ma-handle" />
      <Handle type="source" position={Position.Left} id="ma-source-left" className="flow-handle ma-handle" />
      <Handle type="target" position={Position.Top} id="ma-target-top" className="flow-handle ma-handle" />
      <Handle type="source" position={Position.Top} id="ma-source-top" className="flow-handle ma-handle" />

      <div className="node-card-header master-agent-header">
        <div className="node-card-title-row">
          <span className="node-icon"><NodeIcon kind="master_agent" /></span>
          <span className="node-title">{data.label}</span>
        </div>
        <div className="node-header-badges">
          <span className="chip chip-master-agent">MASTER</span>
          <button
            type="button"
            className="node-delete-btn"
            title="Remove node"
            onClick={(e) => { e.stopPropagation(); data.onDelete?.() }}
          >✕</button>
        </div>
      </div>

      <div className="node-card-body">
        <div className="node-badge-row">
          <span className="chip model-chip">{data.model || data.provider}</span>
          <span className="chip chip-agent-strategy">{STRATEGY_LABELS[data.strategy] ?? data.strategy}</span>
        </div>
        <div className="node-meta-row">
          <span className="meta-item">Max steps: <strong>{data.max_steps}</strong></span>
        </div>
        {data.goal && (
          <div className="node-meta-row">
            <span className="meta-item ma-goal-preview" title={data.goal}>
              🎯 {data.goal.slice(0, 40)}{data.goal.length > 40 ? '…' : ''}
            </span>
          </div>
        )}
      </div>

      <div className="node-card-footer">
        <span className="footer-status ma-footer-status">
          {isCardSelected ? '● Configured in Panel' : 'Connect Child Agents below'}
        </span>
      </div>

      <Handle type="target" position={Position.Right} id="ma-target-right" className="flow-handle ma-handle" />
      <Handle type="source" position={Position.Right} id="ma-source-right" className="flow-handle ma-handle" />
      <Handle type="target" position={Position.Bottom} id="ma-target-bottom" className="flow-handle ma-handle" />
      <Handle type="source" position={Position.Bottom} id="ma-source-bottom" className="flow-handle ma-handle" />
    </div>
  )
}
