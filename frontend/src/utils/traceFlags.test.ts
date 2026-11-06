import { describe, expect, it } from 'vitest'
import type { TraceRecord } from '../types'
import { isSimulated, spanKind } from './traceFlags'

const trace = (metadata_json?: string) => ({ metadata_json }) as TraceRecord

describe('isSimulated', () => {
  it('reads the simulated flag from the trace metadata', () => {
    expect(isSimulated(trace('{"simulated": true, "steps": 1}'))).toBe(true)
    expect(isSimulated(trace('{"steps": 2}'))).toBe(false)
    expect(isSimulated(trace())).toBe(false)
    expect(isSimulated(trace('not json'))).toBe(false)
  })
})

describe('spanKind', () => {
  it('tells model, tool and middleware / retrieval spans apart', () => {
    expect(spanKind('llm').css).toBe('llm')
    expect(spanKind('tool').css).toBe('tool')
    expect(spanKind('retrieval')).toEqual({ css: 'phase', icon: '📚', label: 'Retrieval' })
    expect(spanKind('middleware').label).toBe('Middleware')
    expect(spanKind('embedding').css).toBe('phase')
    expect(spanKind('something-new').css).toBe('tool')
  })
})
