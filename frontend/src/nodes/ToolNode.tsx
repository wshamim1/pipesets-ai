import { Handle, Position, useNodeConnections, useNodesData } from '@xyflow/react'
import type { NodeProps, Node } from '@xyflow/react'
import type { ToolNodeData } from '../types'
import { DebugBadges } from './DebugBadges'
import { callerStatus } from './callerStatus'
import { NodeIcon } from '../components/NodeIcon'

export function ToolNode({ id, data, selected }: NodeProps<Node<ToolNodeData, 'tool'>>) {
  const isCardSelected = selected || data.isSelected
  const connections = useNodeConnections({ id })
  const neighbours = useNodesData(connections.map((c) => (c.source === id ? c.target : c.source)))
  const isMcp = data.toolType === 'mcp'

  return (
    <div className={`tool-node-card ${isMcp ? 'mcp' : ''} ${isCardSelected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left} id="tool-target-left" className="flow-handle tool-handle" />
      <Handle type="source" position={Position.Left} id="tool-source-left" className="flow-handle tool-handle" />
      <Handle type="target" position={Position.Top} id="tool-target-top" className="flow-handle tool-handle" />
      <Handle type="source" position={Position.Top} id="tool-source-top" className="flow-handle tool-handle" />

      <div className="node-card-header tool-header">
        <div className="node-card-title-row">
          <span className="node-icon"><NodeIcon kind={isMcp ? 'mcp' : 'tool'} /></span>
          <span className="node-title">{data.label}</span>
        </div>
        <DebugBadges data={data} />
        <button type="button" className="node-delete-btn" title="Remove node"
          onClick={(e) => { e.stopPropagation(); data.onDelete?.() }}>✕</button>
      </div>

      <div className="node-card-body">
        <div className="node-badge-row">
          <span className={`chip ${isMcp ? 'chip-mcp' : 'chip-tool'}`}>
            {isMcp ? 'MCP PROTOCOL' : 'AGENT TOOL'}
          </span>
        </div>
        <p className="tool-node-desc">{data.description || 'Callable tool for agent workflows.'}</p>
      </div>

      <div className="node-card-footer">
        <span className="footer-status">{isCardSelected ? '● Configured in Panel' : callerStatus(neighbours)}</span>
      </div>

      <Handle type="target" position={Position.Right} id="tool-target-right" className="flow-handle tool-handle" />
      <Handle type="source" position={Position.Right} id="tool-source-right" className="flow-handle tool-handle" />
      <Handle type="target" position={Position.Bottom} id="tool-target-bottom" className="flow-handle tool-handle" />
      <Handle type="source" position={Position.Bottom} id="tool-source-bottom" className="flow-handle tool-handle" />
    </div>
  )
}
