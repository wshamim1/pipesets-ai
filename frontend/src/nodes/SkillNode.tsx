import { Handle, Position, useEdges, useNodes } from '@xyflow/react'
import type { NodeProps, Node } from '@xyflow/react'
import type { FlowEdge, FlowNode, SkillNodeData } from '../types'
import { NodeIcon } from '../components/NodeIcon'
import { describeSkillIssue, skillReadiness, skillTools } from '../utils/skillReadiness'
import { useRequiredConfig } from '../utils/toolCatalog'

/** Whether the skill's tools are on the LLM node it's wired to (and set up), in one line. */
function Readiness({ id }: { id: string }) {
  const nodes = useNodes() as FlowNode[]
  const edges = useEdges() as FlowEdge[]
  const requiredConfig = useRequiredConfig()
  const self = nodes.find((n) => n.id === id)
  if (!self || !skillTools(self).length) return null
  const wired = edges.some((e) => (e.source === id || e.target === id)
    && nodes.find((n) => n.id === (e.source === id ? e.target : e.source))?.type === 'llm')
  if (!wired) return null
  const [issue] = skillReadiness(nodes, edges, requiredConfig, id)
  return issue
    ? <p className="skill-readiness skill-readiness--bad" title={describeSkillIssue(issue)}>⚠ Needs: {describeSkillIssue(issue)}</p>
    : <p className="skill-readiness skill-readiness--ok">✓ Its {skillTools(self).length} tool(s) are attached</p>
}

export function SkillNode({ id, data, selected }: NodeProps<Node<SkillNodeData, 'skill'>>) {
  const isCardSelected = selected || data.isSelected

  return (
    <div className={`tool-node-card skill-node-card ${isCardSelected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left} id="skill-target-left" className="flow-handle tool-handle" />
      <Handle type="source" position={Position.Left} id="skill-source-left" className="flow-handle tool-handle" />
      <Handle type="target" position={Position.Top} id="skill-target-top" className="flow-handle tool-handle" />
      <Handle type="source" position={Position.Top} id="skill-source-top" className="flow-handle tool-handle" />

      <div className="node-card-header skill-node-header">
        <div className="node-card-title-row">
          <span className="node-icon"><NodeIcon kind="skill" /></span>
          <span className="node-title">{data.label || 'Skill'}</span>
        </div>
        <button
          type="button"
          className="node-delete-btn"
          title="Remove skill node"
          onClick={(e) => {
            e.stopPropagation()
            data.onDelete?.()
          }}
        >
          ✕
        </button>
      </div>

      <div className="node-card-body">
        <div className="node-badge-row">
          <span className="chip chip-skill">
            SKILL • {(data.category || 'general').toUpperCase()}
          </span>
        </div>
        <p className="tool-node-desc">
          {data.description || data.instructions?.slice(0, 80) || 'Packaged SOP & capability instructions for agents.'}
        </p>
        <Readiness id={id} />

        {data.tags && data.tags.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
            {data.tags.slice(0, 3).map((tag, idx) => (
              <span
                key={idx}
                style={{
                  fontSize: 10,
                  background: '#fef3c7',
                  color: '#92400e',
                  padding: '1px 5px',
                  borderRadius: 4,
                  border: '1px solid #fde68a',
                  fontWeight: 500,
                }}
              >
                #{tag}
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="node-card-footer">
        <span className="footer-status">{isCardSelected ? '● Configured in Panel' : 'Connect to LLM / Agent'}</span>
      </div>

      <Handle type="target" position={Position.Right} id="skill-target-right" className="flow-handle tool-handle" />
      <Handle type="source" position={Position.Right} id="skill-source-right" className="flow-handle tool-handle" />
      <Handle type="target" position={Position.Bottom} id="skill-target-bottom" className="flow-handle tool-handle" />
      <Handle type="source" position={Position.Bottom} id="skill-source-bottom" className="flow-handle tool-handle" />
    </div>
  )
}
