import type { DebugOverride } from '../components/DebugPauseCard'
import type { DebugNodeFields, FlowNode } from '../types'

/** The run's ``debug`` field (backend services/debug_run.py): breakpoints and pins set on these
 *  nodes, plus a Step request and the paused step's edited input. Undefined when there's nothing,
 *  so ordinary runs are unchanged. */
export function buildDebug(nodeIds: string[], nodes: FlowNode[],
  extra: { step?: boolean; overrides?: Record<string, DebugOverride> } = {}) {
  const ids = new Set(nodeIds)
  const debuggable = nodes.filter((n) => ids.has(n.id)).map((n) => ({ id: n.id, d: n.data as DebugNodeFields }))
  const breakpoints = debuggable.filter(({ d }) => d.debug_breakpoint).map(({ id }) => id)
  const pins = Object.fromEntries(debuggable.filter(({ d }) => d.debug_pin).map(({ id, d }) => [id, d.debug_pin!.output]))
  if (!breakpoints.length && !Object.keys(pins).length && !extra.step && !extra.overrides) return undefined
  return { breakpoints, pins, step: !!extra.step, overrides: extra.overrides ?? {} }
}
