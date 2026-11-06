import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { NodeDebugSection } from './NodeDebugSection'

describe('NodeDebugSection', () => {
  it('opens straight into the pin editor from the node’s 📌', () => {
    render(<NodeDebugSection nodeId="t1" nodeType="tool" data={{}} onUpdate={vi.fn()} startEditing />)
    expect(screen.getByLabelText('Pinned output')).toBeTruthy()
  })

  it('sets a breakpoint and pins a typed output', () => {
    const onUpdate = vi.fn()
    render(<NodeDebugSection nodeId="t1" nodeType="tool" data={{}} onUpdate={onUpdate} />)
    fireEvent.click(screen.getByRole('checkbox'))
    expect(onUpdate).toHaveBeenLastCalledWith('t1', { debug_breakpoint: true })
    fireEvent.click(screen.getByRole('button', { name: '📌 Pin an output' }))
    fireEvent.change(screen.getByLabelText('Pinned output'), { target: { value: '{"rent": 1200}' } })
    fireEvent.click(screen.getByRole('button', { name: 'Pin' }))
    expect(onUpdate.mock.calls.at(-1)![1].debug_pin.output).toBe('{"rent": 1200}')
  })

  it('shows and removes a pin; child agents can be pinned but not paused', () => {
    const onUpdate = vi.fn()
    render(<NodeDebugSection nodeId="c1" nodeType="child_agent" data={{ debug_pin: { output: 'Findings' } }} onUpdate={onUpdate} />)
    expect(screen.queryByRole('checkbox')).toBeNull()
    expect(screen.getByText('Findings')).toBeTruthy()   // the pin's preview
    fireEvent.click(screen.getByRole('button', { name: 'Unpin' }))
    expect(onUpdate).toHaveBeenLastCalledWith('c1', { debug_pin: undefined })
  })
})
