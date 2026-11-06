import type { GatewayNodeData, GatewayKind } from '../../types'
import type { Node } from '@xyflow/react'

interface Props {
  activeNode: Node<GatewayNodeData, 'gateway'>
  onUpdate: (nodeId: string, fields: Record<string, any>) => void
  onDelete: (nodeId: string) => void
  onSave: () => void
  readOnly?: boolean
}

const KIND_OPTIONS: { value: GatewayKind; label: string; icon: string; desc: string }[] = [
  { value: 'condition', icon: '◇', label: 'Condition (IF/ELSE)', desc: 'Routes to true (↓) or false (→) branch based on an expression.' },
  { value: 'merge',     icon: '⊕', label: 'Merge (AND-join)',    desc: 'Waits for all incoming branches before passing through.' },
  { value: 'split',     icon: '⑂', label: 'Split (Fan-out)',     desc: 'Duplicates output to N parallel branches simultaneously.' },
  { value: 'loop',      icon: '↺', label: 'Loop',                desc: 'Repeats connected nodes up to max iterations or until condition is met.' },
]

export function GatewayConfigPanel({ activeNode, onUpdate, onDelete, onSave, readOnly }: Props) {
  const data = activeNode.data

  return (
    <div className="bottom-config-grid">

      {/* 1. Identity & Kind */}
      <div className="config-card">
        <h4 className="card-heading">1. Flow Control Node</h4>
        <div className="form-group">
          <label className="field-label">Node Label</label>
          <input
            type="text"
            className="field-input"
            value={data.label}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { label: e.target.value })}
          />
        </div>
        <div className="form-group">
          <label className="field-label">Type</label>
          <select
            className="field-select"
            value={data.kind}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { kind: e.target.value as GatewayKind })}
          >
            {KIND_OPTIONS.map((k) => (
              <option key={k.value} value={k.value}>{k.icon} {k.label}</option>
            ))}
          </select>
        </div>
        <p className="field-hint">
          {KIND_OPTIONS.find((k) => k.value === data.kind)?.desc ?? ''}
        </p>
      </div>

      {/* 2. Kind-specific config */}
      <div className="config-card">
        <h4 className="card-heading">2. Configuration</h4>

        {data.kind === 'condition' && (
          <>
            <div className="form-group">
              <label className="field-label">Condition Expression</label>
              <input
                type="text"
                className="field-input field-mono"
                placeholder='e.g. output.includes("error")'
                value={data.condition_expr ?? ''}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { condition_expr: e.target.value })}
              />
              <span className="field-hint">JS expression — <code>output</code> holds the upstream text.</span>
            </div>
            <div className="form-group">
              <label className="field-label">True Branch Label</label>
              <input
                type="text"
                className="field-input"
                placeholder="Yes"
                value={data.true_label ?? ''}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { true_label: e.target.value })}
              />
            </div>
            <div className="form-group">
              <label className="field-label">False Branch Label</label>
              <input
                type="text"
                className="field-input"
                placeholder="No"
                value={data.false_label ?? ''}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { false_label: e.target.value })}
              />
            </div>
          </>
        )}

        {data.kind === 'split' && (
          <div className="form-group">
            <label className="field-label">Branch Count (2–5)</label>
            <input
              type="number"
              className="field-input"
              min={2} max={5}
              value={data.branch_count ?? 2}
              disabled={readOnly}
              onChange={(e) => onUpdate(activeNode.id, { branch_count: parseInt(e.target.value, 10) })}
            />
            <span className="field-hint">How many parallel branches to fan out to.</span>
          </div>
        )}

        {data.kind === 'loop' && (
          <>
            <div className="form-group">
              <label className="field-label">Max Iterations</label>
              <input
                type="number"
                className="field-input"
                min={1} max={20}
                value={data.max_iterations ?? 3}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { max_iterations: parseInt(e.target.value, 10) })}
              />
            </div>
            <div className="form-group">
              <label className="field-label">Stop Condition (optional)</label>
              <input
                type="text"
                className="field-input field-mono"
                placeholder='e.g. output.includes("DONE")'
                value={data.loop_condition ?? ''}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { loop_condition: e.target.value })}
              />
              <span className="field-hint">Loop exits early when this expression is truthy.</span>
            </div>
          </>
        )}

        {data.kind === 'merge' && (
          <p className="field-hint" style={{ marginTop: 8 }}>
            Connect multiple incoming edges. The merge node passes through once all upstream branches have completed.
          </p>
        )}
      </div>

      {/* 3. Handle reference */}
      <div className="config-card">
        <h4 className="card-heading">3. Connection Handles</h4>
        <div className="gateway-handle-guide">
          {data.kind === 'condition' && (
            <table className="handle-table">
              <tbody>
                <tr><td>⬅ Left / ⬆ Top</td><td>Incoming</td></tr>
                <tr><td className="handle-true">⬇ Bottom</td><td>True branch</td></tr>
                <tr><td className="handle-false">➡ Right</td><td>False branch</td></tr>
              </tbody>
            </table>
          )}
          {data.kind === 'merge' && (
            <table className="handle-table">
              <tbody>
                <tr><td>⬅ Left / ⬆ Top</td><td>Incoming (multiple)</td></tr>
                <tr><td>➡ Right</td><td>Outgoing (single)</td></tr>
              </tbody>
            </table>
          )}
          {data.kind === 'split' && (
            <table className="handle-table">
              <tbody>
                <tr><td>⬅ Left / ⬆ Top</td><td>Incoming</td></tr>
                <tr><td>⬆ Top / ➡ Right / ⬇ Bottom</td><td>Parallel branches</td></tr>
              </tbody>
            </table>
          )}
          {data.kind === 'loop' && (
            <table className="handle-table">
              <tbody>
                <tr><td>⬅ Left / ⬆ Top</td><td>Incoming</td></tr>
                <tr><td>➡ Right</td><td>Loop exit</td></tr>
                <tr><td className="handle-loop">⬇ Bottom</td><td>Back-edge (loop body)</td></tr>
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* 4. Actions */}
      <div className="config-card">
        <h4 className="card-heading">4. Node Actions</h4>
        <button
          type="button"
          className="save-config-btn"
          disabled={readOnly}
          onClick={onSave}
        >
          Save to App
        </button>
        <button
          type="button"
          className="delete-node-btn"
          disabled={readOnly}
          onClick={() => onDelete(activeNode.id)}
          style={{ marginTop: 8 }}
        >
          Delete Node
        </button>
      </div>

    </div>
  )
}
