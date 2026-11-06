import type { HumanGateNodeData, FlowNode } from '../../types'
import { HelpLink } from '../docs/HelpLink'

interface Props {
  activeNode: FlowNode
  onUpdate: (nodeId: string, fields: Record<string, any>) => void
  onDelete: (nodeId: string) => void
  onSave: () => void
  readOnly?: boolean
}

export function HumanGateConfigPanel({ activeNode, onUpdate, onDelete, onSave, readOnly }: Props) {
  const data = activeNode.data as HumanGateNodeData

  return (
    <div className="bottom-config-grid">
      {/* Card 1 — Identity & Gate Type */}
      <div className="config-card">
        <h4 className="card-heading">1. Identity &amp; Gate Type<HelpLink page="05-agents-workflows-skills" section="human-gate" label="How Human Gates work" /></h4>
        <div className="form-group">
          <label className="field-label">Node Label</label>
          <input type="text" className="field-input" value={data.label} disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { label: e.target.value })} />
        </div>
        <div className="form-group">
          <label className="field-label">Gate Type</label>
          <select className="field-select" value={data.gate_type} disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { gate_type: e.target.value as HumanGateNodeData['gate_type'] })}>
            <option value="approval">Approval — Pipeline pauses until a human approves</option>
            <option value="edit">Edit Gate — Human can edit the output before passing it forward</option>
            <option value="review">Review — Non-blocking; human can flag issues</option>
          </select>
          <span className="field-hint">
            {data.gate_type === 'approval' && 'The pipeline will not continue until the human clicks Approve.'}
            {data.gate_type === 'edit' && 'The pipeline pauses and presents the output for human editing before proceeding.'}
            {data.gate_type === 'review' && 'Sends a notification to the reviewer but does not block the pipeline.'}
          </span>
        </div>
      </div>

      {/* Card 2 — Prompt & Timeout */}
      <div className="config-card">
        <h4 className="card-heading">2. Prompt &amp; Timeout</h4>
        <div className="form-group">
          <label className="field-label">Prompt Message</label>
          <textarea rows={3} className="field-textarea" placeholder="Please review the agent output and approve or reject…"
            value={data.prompt_message} disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { prompt_message: e.target.value })} />
          <span className="field-hint">Message shown to the human reviewer in the notification / UI.</span>
        </div>
        <div className="form-group">
          <label className="field-label">Timeout (hours)</label>
          <input type="number" className="field-input" min="1" max="720" step="1" value={data.timeout_hours}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { timeout_hours: parseInt(e.target.value) || 24 })} />
          <span className="field-hint">If no action is taken within this time, the on-timeout policy applies.</span>
        </div>
      </div>

      {/* Card 3 — Timeout Policy & Actions */}
      <div className="config-card">
        <h4 className="card-heading">3. Timeout Policy &amp; Actions</h4>
        <div className="form-group">
          <label className="field-label">On Timeout</label>
          <select className="field-select" value={data.on_timeout} disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { on_timeout: e.target.value as HumanGateNodeData['on_timeout'] })}>
            <option value="approve">Auto-approve — Continue the pipeline automatically</option>
            <option value="reject">Auto-reject — Stop and mark the run as failed</option>
            <option value="escalate">Escalate — Route to the escalation handler</option>
          </select>
        </div>
        <div className="tool-status-box memory-status-box">
          <span className="status-dot mem-dot" />
          <span>Gate is active — pipeline will pause here awaiting human action.</span>
        </div>
        {!readOnly && (
          <div className="card-actions-row">
            <button type="button" className="save-btn" onClick={onSave}>Save to App</button>
            <button type="button" className="delete-btn" onClick={() => onDelete(activeNode.id)}>Delete Node</button>
          </div>
        )}
      </div>
    </div>
  )
}
