/**
 * 🐞 Debug strip at the top of a node's config (plan.md F6): a breakpoint pauses Prompt Runner runs
 * before this node's steps, and a pinned output is used instead of running the node — no model
 * call, no tool run — so the nodes after it can be tested for free. Both are editor-only:
 * published, API, scheduled and batch runs ignore them. The node's header has the same two
 * buttons (nodes/DebugBadges.tsx); its 📌 opens this strip with the pin editor.
 */
import { useState } from 'react'
import type { DebugNodeFields } from '../../types'

// What "pause here" means for each node type; Child agents can be pinned but not paused (yet)
const PAUSES: Record<string, string> = {
  llm: 'Before each model call, with the messages it is about to send',
  tool: 'Before each call, with the input the model gave it',
  toolkit: 'Before each call to one of its tools',
  retriever: 'Before the search, with the query',
}
const PIN_WHAT: Record<string, string> = {
  llm: 'the answer', tool: 'the tool result', toolkit: 'every tool result', retriever: 'the retrieved context',
  child_agent: 'this agent’s output',
}

export const DEBUGGABLE_NODE_TYPES = new Set(['llm', 'tool', 'toolkit', 'retriever', 'child_agent'])

interface Props {
  nodeId: string
  nodeType: string
  data: DebugNodeFields
  onUpdate: (nodeId: string, fields: Record<string, unknown>) => void
  startEditing?: boolean   // opened from the node's 📌: show the pin editor right away
}

export function NodeDebugSection({ nodeId, nodeType, data, onUpdate, startEditing = false }: Props) {
  const pin = data.debug_pin
  const [editing, setEditing] = useState(startEditing)
  const [draft, setDraft] = useState(pin?.output ?? '')
  const pauses = PAUSES[nodeType]

  const startEdit = () => {
    setDraft(pin?.output ?? '')
    setEditing(true)
  }
  const savePin = () => {
    onUpdate(nodeId, { debug_pin: { output: draft, pinned_at: new Date().toISOString() } })
    setEditing(false)
  }

  return (
    <div className="node-debug-section" role="group" aria-label="Debug">
      <div className="node-debug-bar">
        <span className="node-debug-title">🐞 Debug</span>
        {pauses && (
          <label className={`node-debug-toggle${data.debug_breakpoint ? ' node-debug-toggle--on' : ''}`} title={`${pauses}. Edit it, then Continue or Step.`}>
            <input type="checkbox" checked={!!data.debug_breakpoint}
              onChange={(e) => onUpdate(nodeId, { debug_breakpoint: e.target.checked || undefined })} />
            <span className="node-debug-dot">●</span> Pause here
          </label>
        )}
        {pin && !editing ? (
          <span className="node-debug-pinned" title={pin.output}>
            📌 <strong>Pinned:</strong> <span className="node-debug-preview">{pin.output || '(empty)'}</span>
            <button type="button" className="node-debug-btn" onClick={startEdit}>Edit</button>
            <button type="button" className="node-debug-btn" onClick={() => onUpdate(nodeId, { debug_pin: undefined })}>Unpin</button>
          </span>
        ) : !editing && (
          <button type="button" className="node-debug-btn" title={`Use ${PIN_WHAT[nodeType] ?? 'an output'} you choose instead of running this node`}
            onClick={startEdit}>📌 Pin an output</button>
        )}
        <span className="node-debug-hint">Prompt Runner only — published runs ignore these</span>
      </div>
      {editing && (
        <div className="node-debug-pin">
          <textarea className="field-input node-debug-textarea" rows={4} value={draft} aria-label="Pinned output" autoFocus
            placeholder={`Type ${PIN_WHAT[nodeType] ?? 'the output'} to use instead of running this node…`}
            onChange={(e) => setDraft(e.target.value)} />
          <div className="node-debug-actions">
            <button type="button" className="node-debug-btn node-debug-btn--primary" onClick={savePin}>Pin</button>
            <button type="button" className="node-debug-btn" onClick={() => setEditing(false)}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  )
}
