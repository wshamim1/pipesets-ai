import { Handle, Position, useNodeConnections, useNodesData } from '@xyflow/react'
import type { NodeProps, Node } from '@xyflow/react'
import type { ChildAgentNodeData } from '../types'
import { DebugBadges } from './DebugBadges'
import { NodeIcon } from '../components/NodeIcon'
import { useLatestAppVersion } from '../utils/publishedApps'
import { openPipelinePreview } from '../utils/pipelinePreview'

export function ChildAgentNode({ id, data, selected }: NodeProps<Node<ChildAgentNodeData, 'child_agent'>>) {
  const isCardSelected = selected || data.isSelected
  const latestVersion = useLatestAppVersion(data.kind === 'pipeline' ? data.app_id : undefined)
  const upgradeAvailable = !!data.app_version && !!latestVersion && latestVersion > data.app_version
  // Tool / toolkit / skill nodes wired to this child (what it runs with); typed-in ids only count when none are
  const connections = useNodeConnections({ id })
  const neighbours = useNodesData(connections.map((c) => (c.source === id ? c.target : c.source)))
  const wiredTools = neighbours.filter((n) => n.type === 'tool' || n.type === 'toolkit').length
  const wiredSkills = neighbours.filter((n) => n.type === 'skill').length
  const toolCount = wiredTools || (data.allowed_tool_ids?.length ?? 0)

  return (
    <div className={`child-agent-node-card ${isCardSelected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left} id="ca-target-left" className="flow-handle ca-handle" />
      <Handle type="source" position={Position.Left} id="ca-source-left" className="flow-handle ca-handle" />
      <Handle type="target" position={Position.Top} id="ca-target-top" className="flow-handle ca-handle" />
      <Handle type="source" position={Position.Top} id="ca-source-top" className="flow-handle ca-handle" />

      <div className="node-card-header child-agent-header">
        <div className="node-card-title-row">
          <span className="node-icon"><NodeIcon kind="child_agent" /></span>
          <span className="node-title">{data.label}</span>
        </div>
        <div className="node-header-badges">
          <span className="chip chip-child-agent">
            {data.kind === 'external' ? 'EXTERNAL' : data.kind === 'pipeline' ? 'PIPELINE' : 'CHILD'}
          </span>
          <DebugBadges data={data} canPause={false} />
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
          {data.kind === 'external'
            ? <span className="chip model-chip">{(data.protocol ?? 'openai').toUpperCase()}</span>
            : data.kind === 'pipeline'
              ? <>
                  <span className="chip model-chip">{data.app_version ? `v${data.app_version}` : 'latest'}</span>
                  {upgradeAvailable && (
                    <span className="chip chip-upgrade" title={`v${latestVersion} is available — upgrade in the config panel`}>
                      ★ v{latestVersion}
                    </span>
                  )}
                </>
              : <span className="chip model-chip">{data.model || data.provider}</span>}
          {data.role && <span className="chip chip-agent-role">{data.role.slice(0, 14)}</span>}
        </div>
        {data.kind === 'external' ? (
          <div className="node-meta-row">
            <span className="meta-item ca-prompt-preview" title={data.endpoint_url}>
              {data.endpoint_url || 'No endpoint set'}
            </span>
          </div>
        ) : data.kind === 'pipeline' ? (
          <div className="node-meta-row">
            <span className="meta-item ca-prompt-preview" title={data.app_name}>
              {data.app_id ? (data.app_name || data.app_id) : 'No pipeline selected'}
            </span>
          </div>
        ) : (
          <div className="node-meta-row">
            <span className="meta-item">Tools: <strong>{toolCount}</strong></span>
            {wiredSkills > 0 && <span className="meta-item">Skills: <strong>{wiredSkills}</strong></span>}
          </div>
        )}
        {data.system_prompt && (
          <div className="node-meta-row">
            <span className="meta-item ca-prompt-preview" title={data.system_prompt}>
              {data.system_prompt.slice(0, 38)}{data.system_prompt.length > 38 ? '…' : ''}
            </span>
          </div>
        )}
      </div>

      <div className="node-card-footer">
        <span className="footer-status ca-footer-status">
          {isCardSelected ? '● Configured in Panel' : 'Connect to Master Agent'}
        </span>
        {data.kind === 'pipeline' && data.app_id && (
          <button
            type="button"
            className="node-expand-btn nodrag"
            title="View this pipeline's nodes (read-only)"
            onClick={(e) => {
              e.stopPropagation()
              openPipelinePreview({ appId: data.app_id!, version: data.app_version ?? 0, name: data.app_name || data.label })
            }}
          >⤢ Expand</button>
        )}
      </div>

      <Handle type="target" position={Position.Right} id="ca-target-right" className="flow-handle ca-handle" />
      <Handle type="source" position={Position.Right} id="ca-source-right" className="flow-handle ca-handle" />
      <Handle type="target" position={Position.Bottom} id="ca-target-bottom" className="flow-handle ca-handle" />
      <Handle type="source" position={Position.Bottom} id="ca-source-bottom" className="flow-handle ca-handle" />
    </div>
  )
}
