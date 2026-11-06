import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { DebugBadges } from './DebugBadges'

describe('DebugBadges (on the node)', () => {
  it('toggles a breakpoint and opens the pin editor', () => {
    const onDebugUpdate = vi.fn()
    const onOpenDebug = vi.fn()
    render(<DebugBadges data={{ onDebugUpdate, onOpenDebug }} />)
    fireEvent.click(screen.getByRole('button', { name: '●' }))
    expect(onDebugUpdate).toHaveBeenCalledWith({ debug_breakpoint: true })
    fireEvent.click(screen.getByRole('button', { name: '📌' }))
    expect(onOpenDebug).toHaveBeenCalledWith(true)
  })

  it('shows what is set; a pinned 📌 opens the strip to edit, a set ● removes the breakpoint', () => {
    const onDebugUpdate = vi.fn()
    const onOpenDebug = vi.fn()
    render(<DebugBadges data={{ debug_breakpoint: true, debug_pin: { output: '42' }, onDebugUpdate, onOpenDebug }} />)
    expect(screen.getByRole('button', { name: '●' }).getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(screen.getByRole('button', { name: '●' }))
    expect(onDebugUpdate).toHaveBeenCalledWith({ debug_breakpoint: undefined })
    fireEvent.click(screen.getByRole('button', { name: '📌' }))
    expect(onOpenDebug).toHaveBeenCalledWith(false)
  })

  it('child agents get no breakpoint; published (no callbacks) shows only what is set', () => {
    const { container } = render(<DebugBadges data={{ onDebugUpdate: vi.fn(), onOpenDebug: vi.fn() }} canPause={false} />)
    expect(screen.queryByRole('button', { name: '●' })).toBeNull()
    container.remove()
    const { container: empty } = render(<DebugBadges data={{}} />)
    expect(empty.innerHTML).toBe('')
  })
})
