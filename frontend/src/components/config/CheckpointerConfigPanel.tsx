import type { CheckpointerNodeData, FlowNode } from '../../types'

interface Props {
  activeNode: FlowNode
  onUpdate: (nodeId: string, fields: Record<string, any>) => void
  onDelete: (nodeId: string) => void
  onSave: () => void
  readOnly?: boolean
}

export function CheckpointerConfigPanel({ activeNode, onUpdate, onDelete, onSave, readOnly }: Props) {
  const data = activeNode.data as CheckpointerNodeData

  return (
    <div className="bottom-config-grid">
      {/* Card 1 — Identity & Storage */}
      <div className="config-card">
        <h4 className="card-heading">1. Identity &amp; Storage</h4>
        <div className="form-group">
          <label className="field-label">Node Label</label>
          <input type="text" className="field-input" value={data.label} disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { label: e.target.value })} />
        </div>
        <div className="form-group">
          <label className="field-label">Stored In</label>
          <input type="text" className="field-input" value="App database (SQLite or Postgres)" disabled />
          <span className="field-hint">
            Checkpoints are saved with the run in the server's own database, whichever it is configured to use.
            Provider keys are never saved — a resume sends them again.
          </span>
        </div>
      </div>

      {/* Card 2 — What is saved */}
      <div className="config-card">
        <h4 className="card-heading">2. Save Steps</h4>
        <div className="form-group">
          <label className="field-label">
            <input type="checkbox" checked={data.save_steps} disabled={readOnly}
              onChange={(e) => onUpdate(activeNode.id, { save_steps: e.target.checked })} />{' '}
            Save each finished step
          </label>
          <span className="field-hint">
            {data.save_steps
              ? 'Each model turn and tool result is saved as it finishes. Needed to resume a run where it stopped or re-run it from a step in the trace.'
              : 'Only the run\'s status is kept — no model or tool output. Use it when tool results must not be stored. A resume starts over.'}
          </span>
        </div>
        <span className="field-hint">
          A flow with a Human Gate always saves its steps, so a reviewer's decision applies to the output they reviewed.
        </span>
      </div>

      {/* Card 3 — Resume behaviour & Actions */}
      <div className="config-card">
        <h4 className="card-heading">3. Resume &amp; Actions</h4>
        <div className="form-group">
          <label className="field-label">
            <input type="checkbox" checked={data.save_steps && data.restore_on_resume} disabled={readOnly || !data.save_steps}
              onChange={(e) => onUpdate(activeNode.id, { restore_on_resume: e.target.checked })} />{' '}
            Restore on resume
          </label>
          <span className="field-hint">
            {data.save_steps && data.restore_on_resume
              ? 'Resuming an interrupted or failed run reuses its finished steps: no model call is paid for twice, no tool runs twice.'
              : 'Resuming runs everything again under the same run id — for tools whose results go stale.'}
          </span>
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
