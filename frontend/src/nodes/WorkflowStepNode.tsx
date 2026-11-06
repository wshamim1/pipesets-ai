import { Handle, Position, useNodeConnections, useNodesData } from '@xyflow/react'
import type { NodeProps, Node } from '@xyflow/react'
import type { ToolNodeData, WorkflowStepNodeData } from '../types'
import { NodeIcon } from '../components/NodeIcon'

const WF_STEP_META: Record<WorkflowStepNodeData['step_type'], { tag: string; pauses: boolean }> = {
  ask:       { tag: 'ASK USER',   pauses: true },
  choice:    { tag: 'CHOICE',     pauses: true },
  confirm:   { tag: 'CONFIRM',    pauses: true },
  tool_call: { tag: 'TOOL CALL',  pauses: false },
  message:   { tag: 'MESSAGE',    pauses: false },
}

export function WorkflowStepNode({ id, data, selected }: NodeProps<Node<WorkflowStepNodeData, 'wf_step'>>) {
  const isCardSelected = selected || data.isSelected
  const meta = WF_STEP_META[data.step_type] ?? WF_STEP_META.message
  const connections = useNodeConnections({ id })
  const neighbours = useNodesData(connections.map((c) => (c.source === id ? c.target : c.source)))
  const linkedTool = neighbours.find((n) => n.type === 'tool')?.data as ToolNodeData | undefined
  const toolName = linkedTool ? `${linkedTool.icon} ${linkedTool.label}` : data.tool_id
  const summary = data.step_type === 'tool_call' ? (toolName || 'No tool linked') : (data.prompt || 'No prompt yet')

  return (
    <div className={`wf-step-node-card ${isCardSelected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left}   id="wf-target-left"   className="flow-handle wf-handle" />
      <Handle type="source" position={Position.Left}   id="wf-source-left"   className="flow-handle wf-handle" />
      <Handle type="target" position={Position.Top}    id="wf-target-top"    className="flow-handle wf-handle" />
      <Handle type="source" position={Position.Top}    id="wf-source-top"    className="flow-handle wf-handle" />

      <div className="node-card-header wf-step-header">
        <div className="node-card-title-row">
          <span className="node-icon"><NodeIcon kind="wf_step" variant={data.step_type} /></span>
          <span className="node-title">{data.label}</span>
        </div>
        <button type="button" className="node-delete-btn" title="Remove node"
          onClick={(e) => { e.stopPropagation(); data.onDelete?.() }}>✕</button>
      </div>

      <div className="node-card-body">
        <div className="node-badge-row">
          <span className="chip wf-chip">{meta.tag}</span>
          {data.variable && <span className="chip model-chip">{`{{${data.variable}}}`}</span>}
        </div>
        <div className="wf-step-summary" title={summary}>{summary}</div>
      </div>

      <div className="node-card-footer">
        <span className="footer-status wf-footer-status">
          {isCardSelected ? '● Active in Bottom Config' : meta.pauses ? 'Waits for user reply' : 'Runs automatically'}
        </span>
      </div>

      <Handle type="target" position={Position.Right}  id="wf-target-right"  className="flow-handle wf-handle" />
      <Handle type="source" position={Position.Right}  id="wf-source-right"  className="flow-handle wf-handle" />
      <Handle type="target" position={Position.Bottom} id="wf-target-bottom" className="flow-handle wf-handle" />
      <Handle type="source" position={Position.Bottom} id="wf-source-bottom" className="flow-handle wf-handle" />
    </div>
  )
}
