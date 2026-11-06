import type { WorkflowStepNodeData, FlowNode, FlowEdge } from '../../types'
import { findLinkedTool } from '../../utils/workflowTools'
import { HelpLink } from '../docs/HelpLink'

interface Props {
  activeNode: FlowNode
  nodes: FlowNode[]
  edges: FlowEdge[]
  onUpdate: (nodeId: string, fields: Record<string, any>) => void
  onDelete: (nodeId: string) => void
  onSave: () => void
  readOnly?: boolean
}

const STEP_HINTS: Record<WorkflowStepNodeData['step_type'], string> = {
  ask: 'Asks the user a question and pauses until they reply. The answer is stored in the variable.',
  choice: 'Shows a list of options (from a variable) and pauses until the user picks one.',
  confirm: 'Asks a yes/no question and pauses. Connect "yes" and "no" paths with edge labels (double-click an edge to label it).',
  tool_call: 'Calls a tool / MCP server automatically and stores the result in the variable (or shows it to the user if no variable is set).',
  message: 'Shows a message to the user and continues without waiting.',
}

export function WorkflowStepConfigPanel({ activeNode, nodes, edges, onUpdate, onDelete, onSave, readOnly }: Props) {
  const data = activeNode.data as WorkflowStepNodeData
  const linkedTool = findLinkedTool(activeNode.id, nodes, edges)
  const set = (fields: Partial<WorkflowStepNodeData>) => onUpdate(activeNode.id, fields)
  const t = data.step_type

  return (
    <div className="bottom-config-grid">
      {/* Card 1 — Identity & Step Type */}
      <div className="config-card">
        <h4 className="card-heading">1. Identity &amp; Step Type<HelpLink page="05-agents-workflows-skills" section="workflows-conversational-steps" label="How workflows work" /></h4>
        <div className="form-group">
          <label className="field-label">Node Label</label>
          <input type="text" className="field-input" value={data.label} disabled={readOnly}
            onChange={(e) => set({ label: e.target.value })} />
        </div>
        <div className="form-group">
          <label className="field-label">Step Type</label>
          <select className="field-select" value={t} disabled={readOnly}
            onChange={(e) => set({ step_type: e.target.value as WorkflowStepNodeData['step_type'] })}>
            <option value="ask">Ask — collect a value from the user</option>
            <option value="choice">Choice — pick from a list</option>
            <option value="confirm">Confirm — yes / no</option>
            <option value="tool_call">Tool Call — fetch or act automatically</option>
            <option value="message">Message — show text, no reply</option>
          </select>
          <span className="field-hint">{STEP_HINTS[t]}</span>
        </div>
      </div>

      {/* Card 2 — Prompt & Variable */}
      <div className="config-card">
        <h4 className="card-heading">2. Prompt &amp; Variable</h4>
        {t !== 'tool_call' && (
          <div className="form-group">
            <label className="field-label">Message to User</label>
            <textarea rows={3} className="field-textarea" disabled={readOnly}
              placeholder={t === 'ask' ? 'Which city are you traveling to?' : 'Use {{variable}} to insert earlier answers'}
              value={data.prompt} onChange={(e) => set({ prompt: e.target.value })} />
            <span className="field-hint">Supports {'{{variable}}'} placeholders from earlier steps.</span>
          </div>
        )}
        {t !== 'message' && (
          <div className="form-group">
            <label className="field-label">Save Result As (variable)</label>
            <input type="text" className="field-input" placeholder="location" disabled={readOnly}
              value={data.variable}
              onChange={(e) => set({ variable: e.target.value.replace(/[^A-Za-z0-9_]/g, '_') })} />
            <span className="field-hint">Later steps reference it as {'{{' + (data.variable || 'variable') + '}}'}.</span>
          </div>
        )}
        {t === 'ask' && (
          <div className="form-group">
            <label className="field-label">Expected Input</label>
            <select className="field-select" value={data.input_kind ?? 'text'} disabled={readOnly}
              onChange={(e) => set({ input_kind: e.target.value as WorkflowStepNodeData['input_kind'] })}>
              <option value="text">Text</option>
              <option value="number">Number</option>
              <option value="date">Date</option>
            </select>
          </div>
        )}
      </div>

      {/* Card 3 — Step specifics & actions */}
      <div className="config-card">
        <h4 className="card-heading">3. {t === 'choice' ? 'Options' : t === 'tool_call' ? 'Tool' : 'Behaviour'} &amp; Actions</h4>
        {t === 'choice' && (
          <>
            <div className="form-group">
              <label className="field-label">Options From (variable)</label>
              <input type="text" className="field-input" placeholder="results" disabled={readOnly}
                value={data.options_source ?? ''} onChange={(e) => set({ options_source: e.target.value })} />
              <span className="field-hint">A list produced by an earlier Tool Call step.</span>
            </div>
            <div className="form-group">
              <label className="field-label">Label Field / Value Field</label>
              <div className="wf-two-col">
                <input type="text" className="field-input" placeholder="name" disabled={readOnly}
                  value={data.option_label_field ?? ''} onChange={(e) => set({ option_label_field: e.target.value })} />
                <input type="text" className="field-input" placeholder="id" disabled={readOnly}
                  value={data.option_value_field ?? ''} onChange={(e) => set({ option_value_field: e.target.value })} />
              </div>
            </div>
          </>
        )}
        {t === 'tool_call' && (
          <>
            {linkedTool ? (
              <div className="tool-status-box memory-status-box">
                <span className="status-dot mem-dot" />
                <span>Using linked tool: <strong>{linkedTool.icon} {linkedTool.label}</strong></span>
              </div>
            ) : (
              <>
                <div className="tool-status-box">
                  <span>No tool linked. Drag a tool (e.g. Weather) onto the canvas and connect it to this step — or enter a Tool ID below.</span>
                </div>
                <div className="form-group">
                  <label className="field-label">Tool ID (fallback)</label>
                  <input type="text" className="field-input" placeholder="weather" disabled={readOnly}
                    value={data.tool_id ?? ''} onChange={(e) => set({ tool_id: e.target.value })} />
                </div>
              </>
            )}
            <div className="form-group">
              <label className="field-label">Input to Tool</label>
              <input type="text" className="field-input" placeholder="{{city}}" disabled={readOnly}
                value={data.tool_input ?? ''} onChange={(e) => set({ tool_input: e.target.value })} />
              <span className="field-hint">Text sent to the tool, e.g. {'{{city}}'} for a weather lookup.</span>
            </div>
          </>
        )}
        {(t === 'ask' || t === 'confirm' || t === 'message') && (
          <div className="tool-status-box memory-status-box">
            <span className="status-dot mem-dot" />
            <span>{t === 'message' ? 'Runs automatically, then continues.' : 'Workflow pauses here until the user replies.'}</span>
          </div>
        )}
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
