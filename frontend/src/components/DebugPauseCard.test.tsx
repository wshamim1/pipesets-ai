import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { DebugPauseCard } from './DebugPauseCard'
import type { DebugPause } from './DebugPauseCard'

const toolPause: DebugPause = { run_id: 'r1', step: 'tool:1:0', node_id: 't1', kind: 'tool', label: 'lookup', input: { input: 'x' } }
const llmPause: DebugPause = {
  run_id: 'r1', step: 'llm:2', node_id: 'llm', kind: 'llm', label: 'gpt-x',
  input: { messages: [
    { role: 'system', content: 'Be brief.' },
    { role: 'assistant', content: null, tool_calls: [{ id: 'c1' }] },
    { role: 'tool', content: '42', tool_call_id: 'c1' },
  ] },
}

describe('DebugPauseCard', () => {
  it('continues a tool step with no edit, or steps with the edited input', () => {
    const onContinue = vi.fn()
    render(<DebugPauseCard pause={toolPause} onContinue={onContinue} onStop={vi.fn()} />)
    expect(screen.getByText('lookup')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '▶ Continue' }))
    expect(onContinue).toHaveBeenLastCalledWith(null, false)
    fireEvent.change(screen.getByLabelText('Tool input'), { target: { value: 'y' } })
    fireEvent.click(screen.getByRole('button', { name: '⤵ Step' }))
    expect(onContinue).toHaveBeenLastCalledWith({ input: 'y' }, true)
  })

  it('edits a model call’s message text and keeps the rest of each message', () => {
    const onContinue = vi.fn()
    render(<DebugPauseCard pause={llmPause} onContinue={onContinue} onStop={vi.fn()} />)
    expect(screen.getByText('(tool calls only)')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('tool message 3'), { target: { value: '41' } })
    fireEvent.click(screen.getByRole('button', { name: '▶ Continue' }))
    const [override] = onContinue.mock.calls[0]
    expect(override.messages[2]).toEqual({ role: 'tool', content: '41', tool_call_id: 'c1' })
    expect(override.messages[1]).toEqual(llmPause.input.messages![1])
  })

  it('stops', () => {
    const onStop = vi.fn()
    render(<DebugPauseCard pause={toolPause} onContinue={vi.fn()} onStop={onStop} />)
    fireEvent.click(screen.getByRole('button', { name: '■ Stop' }))
    expect(onStop).toHaveBeenCalled()
  })
})
