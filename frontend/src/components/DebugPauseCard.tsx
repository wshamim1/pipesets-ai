/**
 * A Prompt Runner run paused at a breakpoint (plan.md F6, backend services/debug_run.py): shows the
 * input the paused step is about to use — a tool's input, a model call's messages, the retrieval
 * query — lets the builder edit it, then Continue (to the next breakpoint), Step (pause before the
 * next step, whatever node it is) or Stop. Steps before the pause are replayed from the checkpoint,
 * so continuing never pays for a model call twice.
 */
import { useState } from 'react'

export interface DebugMessage {
  role: string
  content: unknown
  [key: string]: unknown
}

export interface DebugPause {
  run_id: string
  step: string
  node_id: string | null
  kind: 'llm' | 'tool' | 'retriever'
  label: string
  input: { input?: string; query?: string; messages?: DebugMessage[] }
}

/** The step's edited input, keyed as the backend expects it in ``debug.overrides``. */
export type DebugOverride = { input?: string; query?: string; messages?: DebugMessage[] }

const KIND_LABEL: Record<DebugPause['kind'], string> = { llm: 'model call', tool: 'tool call', retriever: 'retrieval' }

interface Props {
  pause: DebugPause
  disabled?: boolean
  onContinue: (override: DebugOverride | null, step: boolean) => void
  onStop: () => void
}

export function DebugPauseCard({ pause, disabled, onContinue, onStop }: Props) {
  const [text, setText] = useState(pause.input.input ?? pause.input.query ?? '')
  const [messages, setMessages] = useState<DebugMessage[]>(pause.input.messages ?? [])

  const override = (): DebugOverride | null => {
    if (pause.kind === 'tool') return text !== (pause.input.input ?? '') ? { input: text } : null
    if (pause.kind === 'retriever') return text !== (pause.input.query ?? '') ? { query: text } : null
    const changed = messages.some((m, i) => m.content !== pause.input.messages?.[i]?.content)
    return changed ? { messages } : null
  }

  return (
    <div className="debug-pause" role="group" aria-label="Paused at a breakpoint">
      <div className="debug-pause-head">
        <span className="debug-pause-title">⏸ Paused before the {KIND_LABEL[pause.kind]}: <strong>{pause.label}</strong></span>
        <code className="debug-pause-step">{pause.step}</code>
      </div>
      {pause.kind === 'llm' ? (
        <div className="debug-pause-messages">
          <span className="debug-pause-hint">Messages the model is about to get — edit any text before continuing:</span>
          {messages.map((m, i) => (
            <label key={i} className="debug-pause-msg">
              <span className="debug-pause-role">{m.role}</span>
              {typeof m.content === 'string' ? (
                <textarea className="debug-pause-input" rows={Math.min(8, Math.max(2, m.content.split('\n').length))}
                  value={m.content} aria-label={`${m.role} message ${i + 1}`}
                  onChange={(e) => setMessages((ms) => ms.map((x, j) => (j === i ? { ...x, content: e.target.value } : x)))} />
              ) : (
                <pre className="debug-pause-readonly">{m.content == null ? '(tool calls only)' : JSON.stringify(m.content, null, 2)}</pre>
              )}
            </label>
          ))}
        </div>
      ) : (
        <label className="debug-pause-msg">
          <span className="debug-pause-hint">{pause.kind === 'tool' ? 'Input the tool is about to get' : 'Search query'} — edit it before continuing:</span>
          <textarea className="debug-pause-input" rows={Math.min(8, Math.max(2, text.split('\n').length))} value={text}
            aria-label={pause.kind === 'tool' ? 'Tool input' : 'Search query'} onChange={(e) => setText(e.target.value)} />
        </label>
      )}
      <div className="debug-pause-actions">
        <button type="button" className="agent-gate-btn agent-gate-btn--approve" disabled={disabled}
          title="Run to the next breakpoint" onClick={() => onContinue(override(), false)}>▶ Continue</button>
        <button type="button" className="agent-gate-btn" disabled={disabled}
          title="Pause again before the next step, whatever node it is" onClick={() => onContinue(override(), true)}>⤵ Step</button>
        <button type="button" className="agent-gate-btn agent-gate-btn--reject" disabled={disabled}
          title="End the run here" onClick={onStop}>■ Stop</button>
      </div>
    </div>
  )
}
