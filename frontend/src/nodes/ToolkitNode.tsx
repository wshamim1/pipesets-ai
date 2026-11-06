import { useCallback, type DragEvent } from 'react'
import { Handle, Position, useNodeConnections, useNodesData } from '@xyflow/react'
import type { NodeProps, Node } from '@xyflow/react'
import type { ToolkitNodeData, ToolCatalogItem } from '../types'
import { DebugBadges } from './DebugBadges'
import { callerStatus } from './callerStatus'
import { NodeIcon } from '../components/NodeIcon'

export function ToolkitNode({ id, data, selected }: NodeProps<Node<ToolkitNodeData, 'toolkit'>>) {
  const isCardSelected = selected || data.isSelected
  const connections = useNodeConnections({ id })
  const neighbours = useNodesData(connections.map((c) => (c.source === id ? c.target : c.source)))
  const subTools = data.subTools || []

  // Accept a tool card dropped directly onto this node
  const onDragOver = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    e.dataTransfer.dropEffect = 'copy'
  }, [])

  const onDrop = useCallback((e: DragEvent<HTMLDivElement>) => {
    const raw = e.dataTransfer.getData('application/univ-tool-data')
    if (!raw) return
    e.preventDefault()
    e.stopPropagation()
    try {
      const toolItem: ToolCatalogItem = JSON.parse(raw)
      data.onDropTool?.(toolItem)
    } catch (err) {
      console.error('Error dropping tool:', err)
    }
  }, [data])

  return (
    <div
      className={`toolkit-node-card ${isCardSelected ? 'selected' : ''}`}
      onDragOver={onDragOver}
      onDrop={onDrop}
    >
      <Handle type="target" position={Position.Left}   id="tk-target-left"   className="flow-handle tool-handle" />
      <Handle type="source" position={Position.Left}   id="tk-source-left"   className="flow-handle tool-handle" />
      <Handle type="target" position={Position.Top}    id="tk-target-top"    className="flow-handle tool-handle" />
      <Handle type="source" position={Position.Top}    id="tk-source-top"    className="flow-handle tool-handle" />

      {/* Header */}
      <div className="node-card-header toolkit-header">
        <div className="node-card-title-row">
          <span className="node-icon"><NodeIcon kind="toolkit" /></span>
          <span className="node-title">{data.label}</span>
        </div>
        <DebugBadges data={data} />
        <button type="button" className="node-delete-btn" title="Remove node"
          onClick={(e) => { e.stopPropagation(); data.onDelete?.() }}>✕</button>
      </div>

      {/* Body */}
      <div className="node-card-body toolkit-body">
        <div className="node-badge-row">
          <span className="chip chip-toolkit">TOOLKIT</span>
          <span className="toolkit-subtool-count">{subTools.length} tool{subTools.length !== 1 ? 's' : ''}</span>
        </div>

        {subTools.length === 0 ? (
          <div className="toolkit-drop-hint">
            Drop tool cards here to add them
          </div>
        ) : (
          <div className="toolkit-subtool-list">
            {subTools.map((st) => (
              <div key={st.toolId} className="toolkit-subtool-chip">
                <span>{st.icon}</span>
                <span className="toolkit-subtool-label">{st.label}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="node-card-footer">
        <span className="footer-status">{isCardSelected ? '● Configured in Panel' : callerStatus(neighbours)}</span>
      </div>

      <Handle type="target" position={Position.Right}  id="tk-target-right"  className="flow-handle tool-handle" />
      <Handle type="source" position={Position.Right}  id="tk-source-right"  className="flow-handle tool-handle" />
      <Handle type="target" position={Position.Bottom} id="tk-target-bottom" className="flow-handle tool-handle" />
      <Handle type="source" position={Position.Bottom} id="tk-source-bottom" className="flow-handle tool-handle" />
    </div>
  )
}
