import { Handle, Position } from '@xyflow/react'
import type { NodeProps, Node } from '@xyflow/react'
import type { GatewayNodeData, GatewayKind } from '../types'

const KIND_META: Record<GatewayKind, { icon: string; color: string; chipLabel: string; chipClass: string }> = {
  condition: { icon: '◇',  color: '#f59e0b', chipLabel: 'IF / ELSE',  chipClass: 'chip-gateway-condition' },
  merge:     { icon: '⊕',  color: '#8b5cf6', chipLabel: 'MERGE',      chipClass: 'chip-gateway-merge'     },
  split:     { icon: '⑂',  color: '#0ea5e9', chipLabel: 'SPLIT',      chipClass: 'chip-gateway-split'     },
  loop:      { icon: '↺',  color: '#10b981', chipLabel: 'LOOP',       chipClass: 'chip-gateway-loop'      },
}

export function GatewayNode({ data, selected }: NodeProps<Node<GatewayNodeData, 'gateway'>>) {
  const isCardSelected = selected || data.isSelected
  const meta = KIND_META[data.kind] ?? KIND_META.condition

  return (
    <div className={`gateway-node-card gateway-${data.kind} ${isCardSelected ? 'selected' : ''}`}>
      {/* incoming handle — left */}
      <Handle type="target" position={Position.Left}  id="gw-target-left"  className="flow-handle" />
      <Handle type="target" position={Position.Top}   id="gw-target-top"   className="flow-handle" />

      <div className="node-card-header">
        <div className="node-card-title-row">
          <span className="gateway-icon" style={{ color: meta.color }}>{meta.icon}</span>
          <span className="node-title">{data.label}</span>
        </div>
        <button type="button" className="node-delete-btn" title="Remove node"
          onClick={(e) => { e.stopPropagation(); data.onDelete?.() }}>✕</button>
      </div>

      <div className="node-card-body gateway-body">
        <span className={`chip ${meta.chipClass}`}>{meta.chipLabel}</span>

        {data.kind === 'condition' && (
          <div className="gateway-detail">
            <span className="gateway-expr">{data.condition_expr || 'expr…'}</span>
          </div>
        )}
        {data.kind === 'split' && (
          <div className="gateway-detail">
            <span className="gateway-expr">{data.branch_count ?? 2} branches</span>
          </div>
        )}
        {data.kind === 'loop' && (
          <div className="gateway-detail">
            <span className="gateway-expr">max {data.max_iterations ?? 3}×</span>
          </div>
        )}
      </div>

      {/* outgoing handles */}
      {data.kind === 'condition' ? (
        <>
          {/* true → bottom, false → right */}
          <Handle type="source" position={Position.Bottom} id="gw-true"  className="flow-handle flow-handle-true"  />
          <Handle type="source" position={Position.Right}  id="gw-false" className="flow-handle flow-handle-false" />
        </>
      ) : data.kind === 'merge' ? (
        /* merge just passes through → one outgoing */
        <Handle type="source" position={Position.Right} id="gw-out" className="flow-handle" />
      ) : data.kind === 'split' ? (
        /* split: top + right + bottom outgoing */
        <>
          <Handle type="source" position={Position.Top}    id="gw-split-0" className="flow-handle" />
          <Handle type="source" position={Position.Right}  id="gw-split-1" className="flow-handle" />
          <Handle type="source" position={Position.Bottom} id="gw-split-2" className="flow-handle" />
        </>
      ) : (
        /* loop: back-edge (left/bottom) + exit (right) */
        <>
          <Handle type="source" position={Position.Right}  id="gw-loop-exit" className="flow-handle" />
          <Handle type="source" position={Position.Bottom} id="gw-loop-back" className="flow-handle flow-handle-loop" />
        </>
      )}
    </div>
  )
}
