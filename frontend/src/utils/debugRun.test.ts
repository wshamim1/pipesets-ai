import { describe, expect, it } from 'vitest'
import type { FlowNode } from '../types'
import { buildDebug } from './debugRun'

const node = (id: string, data: Record<string, unknown>) => ({ id, type: 'tool', position: { x: 0, y: 0 }, data }) as unknown as FlowNode

describe('buildDebug', () => {
  const nodes = [
    node('llm', { label: 'LLM', debug_breakpoint: true }),
    node('t1', { label: 'Lookup', debug_pin: { output: '42' } }),
    node('t2', { label: 'Other' }),
    node('far', { label: 'Not connected', debug_breakpoint: true, debug_pin: { output: 'x' } }),
  ]

  it('collects breakpoints and pins from the run’s nodes only', () => {
    expect(buildDebug(['llm', 't1', 't2'], nodes)).toEqual({ breakpoints: ['llm'], pins: { t1: '42' }, step: false, overrides: {} })
  })

  it('is undefined when nothing is set, so ordinary runs are unchanged', () => {
    expect(buildDebug(['t2'], nodes)).toBeUndefined()
  })

  it('carries a Step request and the paused step’s edit', () => {
    expect(buildDebug(['t2'], nodes, { step: true, overrides: { 'tool:1:0': { input: 'y' } } }))
      .toEqual({ breakpoints: [], pins: {}, step: true, overrides: { 'tool:1:0': { input: 'y' } } })
  })
})
